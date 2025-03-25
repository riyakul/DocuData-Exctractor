import json
import os
import logging
from typing import Dict, List, Tuple, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("code_processor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BuildingCodeProcessor")

class BuildingCodeProcessor:
    """Main class for processing building codes with location and keyword filtering."""
    
    def __init__(self, input_file: str):
        self.input_file = input_file
        self.data = self._load_data()
        self.countries = self.data.get('countries', [])
        self.regions = self.data.get('regions', [])
        self.cities = self.data.get('cities', [])
        self.codes = self.data.get('codes', [])
        
        # Fields to remove during pruning
        self.fields_to_remove = {
            "buildingTypeIds", "url", "section_url", "subsection_url",
            "subsubsection_url", "adopted_by", "created_at", "updated_at",
            "parent_id", "child_ids", "regionId", "countryId", "cityId",
            "codeId", "sectionId", "subsectionId", "chapter_url", "projectTypeIds"
        }
        
        # Fields that should always be kept regardless of fields_to_remove
        self.fields_to_keep = {
            'id', 'code', 'code_version', 'effective_date', 'title', 'content', 
            'chapters', 'sections', 'subsections', 'subsubsections', 
            'table_data', 'chapter', 'section'
        }

    def _load_data(self) -> Dict:
        """Load and validate JSON data."""
        try:
            if not os.path.exists(self.input_file):
                raise FileNotFoundError(f"File not found: {self.input_file}")
                
            with open(self.input_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"Loaded data from {self.input_file}")
                return data
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format: {str(e)}")
            raise ValueError(f"Invalid JSON format: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to load data: {str(e)}")
            raise ValueError(f"Failed to load data: {str(e)}")

    def filter_by_location(self, city: str, region: str, country: str) -> List[Dict]:
        """Filter codes by geographic location."""
        logger.info(f"Filtering codes for location: {city}, {region}, {country}")
        
        country_id = self._find_country_id(country)
        if not country_id:
            logger.error(f"Country not found: {country}")
            raise ValueError(f"Country '{country}' not found")
        
        region_id = self._find_region_id(region, country_id)
        if not region_id:
            logger.error(f"Region not found: {region} in country {country}")
            raise ValueError(f"Region '{region}' not found in {country}")
        
        city_id = self._find_city_id(city, region_id)
        if not city_id:
            logger.error(f"City not found: {city} in region {region}")
            raise ValueError(f"City '{city}' not found in {region}")
        
        filtered_codes = [
            code for code in self.codes 
            if 'adopted_by' in code and city_id in set(code['adopted_by'])
        ]
        
        logger.info(f"Found {len(filtered_codes)} codes for location")
        return filtered_codes

    def filter_by_keyword(self, codes: List[Dict], keyword: str) -> Tuple[List[Dict], Dict]:
        """Filter codes by keyword presence in content."""
        keyword = keyword.lower()
        filtered = []
        matches = {}
        
        for code in codes:
            code_matches = self._find_keyword_matches(code, keyword)
            if code_matches:
                filtered.append(code)
                code_id = code.get('id') or code.get('code', 'Unknown')
                matches[code_id] = code_matches
        return filtered, matches

    def _find_keyword_matches(self, code: Dict, keyword: str) -> List[str]:
        """Recursively search for keyword in code structure."""
        matches = []
        
        def search_node(node: Dict, path: str = ""):
            if 'title' in node and keyword in node['title'].lower():
                matches.append(f"{path}Title: {node['title']}")
            if 'content' in node and keyword in node['content'].lower():
                matches.append(f"{path}Content")
                
            for child_type in ['chapters', 'sections', 'subsections', 'subsubsections']:
                for idx, child in enumerate(node.get(child_type, [])):
                    new_path = f"{path}{child_type[:3].upper()}{idx+1}/"
                    search_node(child, new_path)
        
        search_node(code, "CODE/")
        return matches

    def prune_data(self, data: Any) -> Any:
        """Selectively prune fields from data while preserving important ones."""
        if isinstance(data, list):
            return [self.prune_data(item) for item in data]
        if not isinstance(data, dict):
            return data
            
        pruned_data = {}
        for key, value in data.items():
            if key in self.fields_to_keep or key not in self.fields_to_remove:
                pruned_data[key] = self.prune_data(value)
        
        return pruned_data

    def present_code_selection(self, codes: List[Dict]) -> List[Dict]:
        """Present available codes to user and let them choose which to process."""
        if not codes:
            return []
            
        print(f"\n{' AVAILABLE CODES ':=^60}")
        print(f"{'#':<4} {'Code Name':<35} {'Version':<10} {'Date':<12}")
        print(f"{'':-^60}")
        
        for idx, code in enumerate(codes, 1):
            name = code.get('code', 'Unnamed Code')[:35]
            version = code.get('code_version', 'N/A')
            date = code.get('effective_date', 'N/A')
            print(f"{idx:<4} {name:<35} {version:<10} {date:<12}")
        
        print(f"{'':-^60}")
        print("Enter numbers of codes to include (comma-separated) or 'all' for all codes")
        selection = input("Selection: ").strip().lower()
        
        if selection == 'all':
            return codes
            
        try:
            indices = [int(idx.strip()) for idx in selection.split(',') if idx.strip()]
            selected_codes = [codes[idx-1] for idx in indices if 1 <= idx <= len(codes)]
            
            if not selected_codes:
                print("No valid codes selected. Using all codes.")
                return codes
            return selected_codes
        except (ValueError, IndexError):
            print("Invalid selection. Using all codes.")
            return codes
        
    def generate_report(self, codes: List[Dict], matches: Dict, highlight: bool = False) -> str:
        """Generate formatted text report with optional highlighting."""
        report = []
        
        for code in codes:
            header = self._format_header(code)
            report.append(header)
            
            code_id = code.get('id') or code.get('code')
            if code_id and code_id in matches:
                report.append("\n## Keyword Matches Found In:")
                report.extend(f"- {match}" for match in matches[code_id])
                
            report.extend(self._extract_content(code))
            report.append("\n" + "="*50 + "\n")
        
        return '\n'.join(report)

    def _format_header(self, code: Dict) -> str:
        """Format code header information."""
        parts = []
        if code.get('code'):
            parts.append(code['code'])
        if code.get('code_version'):
            parts.append(f"v{code['code_version']}")
        if code.get('effective_date'):
            parts.append(f"Effective {code['effective_date']}")
        return f"# {' | '.join(parts)}"

    def _extract_content(self, node: Dict, depth: int = 2) -> List[str]:
        """Recursively extract content from document structure, including table data."""
        content = []
        headers = ['chapters', 'sections', 'subsections', 'subsubsections']
        
        def process_node(n: Dict, level: int):
            if n.get('title'):
                content.append(f"\n{'#' * level} {n['title']}")
            if n.get('content'):
                content.append(n['content'].strip())
            
            # Simply include table data if present
            if n.get('table_data'):
                table = n.get('table_data', [])
                if table:
                    content.append("\n**TABLE DATA:**")
                    content.append(json.dumps(table, indent=2))
            
            for header in headers:
                for child in n.get(header, []):
                    process_node(child, level + 1)
        
        process_node(node, depth)
        return content

    def _find_country_id(self, country: str) -> Optional[str]:
        for c in self.countries:
            if c['name'].lower() == country.lower():
                return c['id']
        return None

    def _find_region_id(self, region: str, country_id: str) -> Optional[str]:
        for r in self.regions:
            if r['name'].lower() == region.lower() and r['countryId'] == country_id:
                return r['id']
        return None

    def _find_city_id(self, city: str, region_id: str) -> Optional[str]:
        for c in self.cities:
            if c['name'].lower() == city.lower() and c['regionId'] == region_id:
                return c['id']
        return None

    def list_available_codes(self, city: str, state: str, country: str, keyword: Optional[str] = None) -> List[Dict]:
        """List available building codes filtered by location and optionally by keyword."""
        logger.info(f"Listing codes for {city}, {state}, {country} with keyword: {keyword}")
        
        location_codes = self.filter_by_location(city, state, country)
        
        if keyword:
            filtered_codes, matches = self.filter_by_keyword(location_codes, keyword)
        else:
            filtered_codes = location_codes
            matches = {}

        available_codes = []
        for i, code in enumerate(filtered_codes, 1):
            available_codes.append({
                "id": code.get("id", f"unknown_{i}"),
                "index": i,
                "name": code.get("code", "Untitled Code"),
                "version": code.get("code_version", "Unknown"),
                "date": code.get("effective_date", "Unknown date"),
                "matches": matches.get(code.get("id", f"unknown_{i}"), [])
            })

        logger.info(f"Found {len(available_codes)} available codes")
        return available_codes

    def process_selected_codes(self, codes: List[Dict], selected_indices: List[int], keyword: Optional[str] = None) -> Tuple[List[Dict], Dict]:
        """Process selected codes and return pruned codes with matches."""
        valid_codes = []
        matches = {}
        
        for idx in selected_indices:
            if 0 <= idx - 1 < len(codes):
                code = codes[idx - 1]
                valid_codes.append(code)
                
                if keyword:
                    code_matches = self._find_keyword_matches(code, keyword)
                    if code_matches:
                        code_id = code.get('id') or code.get('code', f"unknown_{idx}")
                        matches[code_id] = code_matches

        pruned_codes = self.prune_data(valid_codes)
        return pruned_codes, matches


class LLMQueryEngine:
    """A class for querying building codes using LLM."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the LLM query engine."""
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key,
                                base_url="https://openrouter.ai/api/v1",
                               ) if api_key else None
            self.model = "deepseek/deepseek-chat:free"
        except ImportError as e:
            logger.warning(f"OpenAI module not available: {e}")
            self.client = None

    def query(self, document_text: str, user_query: str, location: str) -> str:
        """Process a user query about building codes using LLM."""
        if not self.client:
            logger.warning("LLM querying unavailable - no API key provided")
            return self._keyword_query(document_text, user_query, location)

        try:
            prompt = self._create_prompt(document_text, user_query, location)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a building code expert assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM query failed: {str(e)}")
            return self._keyword_query(document_text, user_query, location)

    def _create_prompt(self, document_text: str, user_query: str, location: str) -> str:
        """Create a well-structured prompt for the LLM."""
        max_length = 500000  
        truncated_text = document_text[:max_length]
        
        return f"""Based on the building codes for {location}, please answer the following question:

Question: {user_query}

Relevant building code information:

{truncated_text}

Please provide a clear and concise answer based strictly on the building codes above.
Include specific references to relevant sections if possible.
Understand the data presented and tables if present carefully and answer the question accurately.
If the information is not present in the provided codes, clearly state this.
Give me the output in markdown with proper headings and sub-headings so that it can be easily read."""

    def _keyword_query(self, document_text: str, user_query: str, location: str) -> str:
        """Fallback keyword-based query method."""
        paragraphs = document_text.split('\n\n')
        relevant_paragraphs = [
            para for para in paragraphs
            if any(term in para.lower() for term in user_query.lower().split())
        ]

        if not relevant_paragraphs:
            return f"No specific information found about '{user_query}' in the building codes for {location}."

        response = f"Found the following relevant information for '{user_query}' in {location}:\n\n"
        response += "\n\n".join(relevant_paragraphs[:3])
        
        if len(relevant_paragraphs) > 3:
            response += f"\n\n...and {len(relevant_paragraphs) - 3} more relevant sections."
        
        return response


def interactive_llm_query(report_text: str, location: str):
    """Run interactive LLM query session on the building code report."""
    print(f"\n{' LLM QUERY MODE ':=^60}")
    print("You can now ask questions about the building codes for this location.")
    print("Type 'exit' or 'quit' to end the session.")
    print(f"{'':-^60}")
    
    llm_engine = LLMQueryEngine()
    
    while True:
        query = input("\nEnter your question: ").strip()
        if query.lower() in ('exit', 'quit', 'q'):
            break
            
        if not query:
            continue
        
        print("\nQuerying LLM, please wait...")
        try:
            response = llm_engine.query(report_text, query, location)
            print(f"\n{' ANSWER ':=^60}")
            print(response)
            print(f"{'':-^60}")
        except Exception as e:
            print(f"Error: {str(e)}")
