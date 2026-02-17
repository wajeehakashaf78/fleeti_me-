"""
MongoDB Handler for Fleet Analytics Chatbot
Executes MongoDB queries to fetch asset and driver information
"""

from typing import List, Dict, Any
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from config import settings
from models import AssetInfo, DriverInfo


class MongoDBHandler:
    """Handles MongoDB operations"""
    
    def __init__(self):
        """Initialize MongoDB client"""
        self.client = MongoClient(settings.MONGO_URI)
    
    def get_asset_ids_by_plate_numbers(
        self, 
        db_name: str, 
        plate_numbers: List[str]
    ) -> Dict[str, Any]:
        """
        Retrieve asset IDs by plate numbers
        
        Args:
            db_name: Database name
            plate_numbers: List of asset plate numbers
            
        Returns:
            Dictionary with asset information
        """
        try:
            db = self.client[db_name]
            
            # Execute aggregation query
            pipeline = [
                {
                    "$match": {
                        "details.plate_number": {"$in": plate_numbers}
                    }
                },
                {
                    "$project": {
                        "_id": 1,
                        "plate_number": "$details.plate_number"
                    }
                }
            ]
            
            print(f"\n--- MongoDB Query (Asset by Plate Numbers) ---")
            print(f"Database: {db_name}")
            print(f"Collection: Asset")
            print(f"Pipeline: {pipeline}")
            
            results = list(db.Asset.aggregate(pipeline))
            
            # Convert ObjectId to string
            for result in results:
                result["_id"] = str(result["_id"])
            
            print(f"\n--- MongoDB Query Result ---")
            print(f"Found {len(results)} asset(s)")
            print(f"Results: {results}")
            
            return {
                "success": True,
                "count": len(results),
                "assets": results,
                "asset_ids": [r["_id"] for r in results]
            }
            
        except PyMongoError as e:
            print(f"\n--- MongoDB Query Error ---")
            print(f"Error: {str(e)}")
            return {
                "success": False,
                "error": f"MongoDB error: {str(e)}",
                "assets": [],
                "asset_ids": []
            }
    
    def get_asset_ids_by_group_names(
        self, 
        db_name: str, 
        group_names: List[str]
    ) -> Dict[str, Any]:
        """
        Retrieve asset IDs by group names
        
        Args:
            db_name: Database name
            group_names: List of group names
            
        Returns:
            Dictionary with asset information
        """
        try:
            db = self.client[db_name]
            
            # Execute aggregation query
            pipeline = [
                {"$match": {"name": {"$in": group_names}}},
                {"$unwind": "$assigned_assets"},
                {
                    "$project": {
                        "_id": 0,
                        "deviceGroup": "$name",
                        "asset_id": "$assigned_assets.asset_id"
                    }
                }
            ]
            
            print(f"\n--- MongoDB Query (Asset by Group Names) ---")
            print(f"Database: {db_name}")
            print(f"Collection: AssetGroup")
            print(f"Pipeline: {pipeline}")
            
            results = list(db.AssetGroup.aggregate(pipeline))
            
            # Convert ObjectId to string
            for result in results:
                result["asset_id"] = str(result["asset_id"])
            
            print(f"\n--- MongoDB Query Result ---")
            print(f"Found {len(results)} asset(s)")
            print(f"Results: {results}")
            
            return {
                "success": True,
                "count": len(results),
                "assets": results,
                "asset_ids": [r["asset_id"] for r in results]
            }
            
        except PyMongoError as e:
            print(f"\n--- MongoDB Query Error ---")
            print(f"Error: {str(e)}")
            return {
                "success": False,
                "error": f"MongoDB error: {str(e)}",
                "assets": [],
                "asset_ids": []
            }
    
    def get_driver_ids_by_names(
        self, 
        db_name: str, 
        driver_names: List[str]
    ) -> Dict[str, Any]:
        """
        Retrieve driver IDs by driver names
        
        Args:
            db_name: Database name
            driver_names: List of driver full names
            
        Returns:
            Dictionary with driver information
        """
        try:
            db = self.client[db_name]
            
            # Execute aggregation query
            pipeline = [
                {
                    "$match": {
                        "$expr": {
                            "$in": [
                                {"$concat": ["$profile.first_name", " ", "$profile.last_name"]},
                                driver_names
                            ]
                        }
                    }
                },
                {"$unwind": "$asset_assignments"},
                {
                    "$project": {
                        "_id": 0,
                        "driver_id": "$_id",
                        "driver_name": {"$concat": ["$profile.first_name", " ", "$profile.last_name"]},
                        "assignment_id": "$asset_assignments._id"
                    }
                }
            ]
            
            print(f"\n--- MongoDB Query (Driver by Names) ---")
            print(f"Database: {db_name}")
            print(f"Collection: Driver")
            print(f"Pipeline: {pipeline}")
            
            results = list(db.Driver.aggregate(pipeline))
            
            # Convert ObjectId to string
            for result in results:
                result["driver_id"] = str(result["driver_id"])
                if "assignment_id" in result:
                    result["assignment_id"] = str(result["assignment_id"])
            
            print(f"\n--- MongoDB Query Result ---")
            print(f"Found {len(results)} driver(s)")
            print(f"Results: {results}")
            
            return {
                "success": True,
                "count": len(results),
                "drivers": results,
                "driver_ids": [r["driver_id"] for r in results]
            }
            
        except PyMongoError as e:
            print(f"\n--- MongoDB Query Error ---")
            print(f"Error: {str(e)}")
            return {
                "success": False,
                "error": f"MongoDB error: {str(e)}",
                "drivers": [],
                "driver_ids": []
            }
    
    def close(self):
        """Close MongoDB connection"""
        self.client.close()


# Global MongoDB handler instance
mongo_handler = MongoDBHandler()
