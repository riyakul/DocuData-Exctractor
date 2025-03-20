# import json
# from pymongo import MongoClient

# # 1. Connect to MongoDB Atlas
# uri = "mongodb+srv://riyamkulkarni:sGStH59h0EPjdgcc@jsoncluster.yjuh1.mongodb.net/?retryWrites=true&w=majority&appName=JsonCluster"
# client = MongoClient(uri)
# db = client["CombinedJson"]
# collection = db["codes_db_final"]

# # 2. Load local JSON file
# with open("D:\Augrade\codes_db_final (3).json", "r") as f:
#     data = json.load(f)

# # 3. Insert data into MongoDB
# if isinstance(data, list):
#     collection.insert_many(data)
#     print(f"Inserted {len(data)} documents.")
# else:
#     collection.insert_one(data)
#     print("Inserted 1 document.")






import json
import logging
from pymongo import MongoClient, errors
import sys
import os

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def upload_json_to_mongodb(json_file_path, mongo_uri, db_name, collection_name):
    """
    Upload a local JSON file to MongoDB Atlas.

    :param json_file_path: Path to the local JSON file.
    :param mongo_uri: The MongoDB Atlas connection string (including credentials).
    :param db_name: Name of the MongoDB database.
    :param collection_name: Name of the MongoDB collection.
    """
    # 1. Connect to MongoDB
    try:
        logging.info("Connecting to MongoDB...")
        client = MongoClient("mongodb+srv://riyamkulkarni:sGStH59h0EPjdgcc@jsoncluster.yjuh1.mongodb.net/?retryWrites=true&w=majority&appName=JsonCluster")
        db = client["CombinedJson"]
        collection = db["codes_db_final"]
        logging.info(f"Connected to database '{"CombinedJson"}', collection '{"codes_db_final"}'.")
    except errors.ConnectionFailure as e:
        logging.error("Could not connect to MongoDB Atlas.")
        logging.error(e)
        sys.exit(1)

    # 2. Load local JSON file
    try:
        logging.info(f"Loading data from file: {json_file_path}")
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logging.error(f"File not found: {json_file_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON format in file: {json_file_path}")
        logging.error(e)
        sys.exit(1)

    # 3. Insert data into MongoDB
    try:
        if isinstance(data, list):
            logging.info("Detected a list of documents. Inserting with insert_many()...")
            result = collection.insert_many(data)
            logging.info(f"Inserted {len(result.inserted_ids)} documents into '{collection_name}'.")
        else:
            logging.info("Detected a single document. Inserting with insert_one()...")
            result = collection.insert_one(data)
            logging.info(f"Inserted 1 document into '{collection_name}' (ID: {result.inserted_id}).")
    except errors.PyMongoError as e:
        logging.error("Error during insertion into MongoDB.")
        logging.error(e)
    finally:
        client.close()
        logging.info("MongoDB connection closed.")

if __name__ == "__main__":
    # Example usage (replace with your own file path, credentials, DB, and collection):
    JSON_FILE_PATH = r"D:\Augrade\codes_db_final (3).json"
    MONGO_URI = (
        "mongodb+srv://riyamkulkarni:sGStH59h0EPjdgcc@jsoncluster.yjuh1.mongodb.net/retryWrites=true&w=majority&appName=JsonCluster"
    )
    DB_NAME = "CombinedJson"
    COLLECTION_NAME = "codes_db_final"

    upload_json_to_mongodb(JSON_FILE_PATH, MONGO_URI, DB_NAME, COLLECTION_NAME)
