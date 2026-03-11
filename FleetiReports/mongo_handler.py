"""
MongoDB Handler for Fleet Analytics Chatbot
Executes MongoDB queries to fetch asset and driver information
"""

from typing import List, Dict, Any
import re
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from .config import settings
from .models import AssetInfo, DriverInfo


class MongoDBHandler:
    """Handles MongoDB operations"""
    
    def __init__(self):
        """Initialize MongoDB client"""
        self.client = MongoClient(settings.MONGO_URI)

    def _normalize_plate(self, plate: str) -> str:
        """Normalize plate by removing separators and uppercasing."""
        if not plate:
            return ""
        return re.sub(r"[^A-Za-z0-9]", "", plate).upper()

    def _build_plate_variants(self, plate_numbers: List[str]) -> List[str]:
        """
        Build normalized matching variants for each plate.
        Example:
        - LED 4556 -> LED4556, 4556LED
        - 4556-LED -> 4556LED, LED4556
        """
        variants = set()
        for plate in plate_numbers or []:
            if not plate:
                continue
            normalized = self._normalize_plate(plate)
            if normalized:
                variants.add(normalized)

            tokens = [t.upper() for t in re.findall(r"[A-Za-z0-9]+", plate)]
            if len(tokens) >= 2:
                forward = "".join(tokens)
                reverse = "".join(reversed(tokens))
                if forward:
                    variants.add(forward)
                if reverse:
                    variants.add(reverse)
        return list(variants)

    def _is_all_selector(self, values: List[str] | None) -> bool:
        """Return True if any provided selector value is 'ALL' (case-insensitive)."""
        return any(str(v).strip().upper() == "ALL" for v in (values or []))

    def _unique_strings(self, values: List[str]) -> List[str]:
        """Deduplicate while preserving order."""
        seen = set()
        unique = []
        for value in values:
            key = str(value)
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique
    
    def get_asset_ids_by_plate_numbers(
        self, 
        db_name: str, 
        plate_numbers: List[str],
        sub_tenant_id: str | None = None
    ) -> Dict[str, Any]:
        """
        Retrieve asset IDs by plate numbers
        
        Args:
            db_name: Database name
            plate_numbers: List of asset plate numbers
            sub_tenant_id: Sub-tenant identifier from JWT for tenant scoping
            
        Returns:
            Dictionary with asset information
        """
        try:
            db = self.client[db_name]
            all_assets_requested = self._is_all_selector(plate_numbers)
            normalized_variants = self._build_plate_variants(plate_numbers)

            if all_assets_requested:
                match_stage: Dict[str, Any] = {}
                if sub_tenant_id:
                    match_stage["sub_tenant_id"] = sub_tenant_id

                pipeline = []
                if match_stage:
                    pipeline.append({"$match": match_stage})
                pipeline.append({
                    "$project": {
                        "_id": 1,
                        "plate_number": "$details.plate_number"
                    }
                })
            else:
                # Execute aggregation query by specific plate values.
                match_stage = {
                    "_normalized_plate": {"$in": normalized_variants}
                }
                if sub_tenant_id:
                    match_stage["sub_tenant_id"] = sub_tenant_id

                pipeline = [
                    {
                        "$addFields": {
                            "_normalized_plate": {
                                "$toUpper": {
                                    "$replaceAll": {
                                        "input": {
                                            "$replaceAll": {
                                                "input": {
                                                    "$replaceAll": {
                                                        "input": "$details.plate_number",
                                                        "find": " ",
                                                        "replacement": ""
                                                    }
                                                },
                                                "find": "-",
                                                "replacement": ""
                                            }
                                        },
                                        "find": "_",
                                        "replacement": ""
                                    }
                                }
                            }
                        }
                    },
                    {
                        "$match": match_stage
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
            print(f"SubTenantId: {sub_tenant_id}")
            print(f"AllAssetsRequested: {all_assets_requested}")
            print(f"Normalized Variants: {normalized_variants}")
            print(f"Pipeline: {pipeline}")
            
            results = list(db.Asset.aggregate(pipeline))
            
            # Convert ObjectId to string
            for result in results:
                result["_id"] = str(result["_id"])
            
            print(f"\n--- MongoDB Query Result ---")
            print(f"Found {len(results)} asset(s)")
            print(f"Results: {results}")

            asset_ids = self._unique_strings([r["_id"] for r in results])
            
            return {
                "success": True,
                "count": len(results),
                "assets": results,
                "asset_ids": asset_ids
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
        group_names: List[str],
        sub_tenant_id: str | None = None
    ) -> Dict[str, Any]:
        """
        Retrieve asset IDs by group names
        
        Args:
            db_name: Database name
            group_names: List of group names
            sub_tenant_id: Sub-tenant identifier from JWT for tenant scoping
            
        Returns:
            Dictionary with asset information
        """
        try:
            db = self.client[db_name]
            all_groups_requested = self._is_all_selector(group_names)

            if all_groups_requested:
                group_match: Dict[str, Any] = {}
                if sub_tenant_id:
                    group_match["sub_tenant_id"] = sub_tenant_id
            else:
                group_match = {"name": {"$in": group_names}}
                if sub_tenant_id:
                    group_match["sub_tenant_id"] = sub_tenant_id

            pipeline = []
            if group_match:
                pipeline.append({"$match": group_match})
            pipeline.extend([
                {"$unwind": "$assigned_assets"},
                {
                    "$project": {
                        "_id": 0,
                        "group_id": "$_id",
                        "deviceGroup": "$name",
                        "asset_id": "$assigned_assets.asset_id"
                    }
                }
            ])
            
            print(f"\n--- MongoDB Query (Asset by Group Names) ---")
            print(f"Database: {db_name}")
            print(f"Collection: AssetGroup")
            print(f"SubTenantId: {sub_tenant_id}")
            print(f"AllGroupsRequested: {all_groups_requested}")
            print(f"Pipeline: {pipeline}")
            
            results = list(db.AssetGroup.aggregate(pipeline))
            
            # Convert ObjectId to string
            for result in results:
                result["asset_id"] = str(result["asset_id"])
                if "group_id" in result:
                    result["group_id"] = str(result["group_id"])
            
            print(f"\n--- MongoDB Query Result ---")
            print(f"Found {len(results)} asset(s)")
            print(f"Results: {results}")

            asset_ids = self._unique_strings([r["asset_id"] for r in results])
            group_ids = self._unique_strings([r["group_id"] for r in results if r.get("group_id") is not None])
            
            return {
                "success": True,
                "count": len(results),
                "assets": results,
                "asset_ids": asset_ids,
                "group_ids": group_ids
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
        driver_names: List[str],
        sub_tenant_id: str | None = None
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
            all_drivers_requested = self._is_all_selector(driver_names)

            if all_drivers_requested:
                match_stage: Dict[str, Any] = {}
                if sub_tenant_id:
                    match_stage["sub_tenant_id"] = sub_tenant_id

                pipeline = []
                if match_stage:
                    pipeline.append({"$match": match_stage})
                pipeline.append({
                    "$project": {
                        "_id": 0,
                        "driver_id": "$_id",
                        "driver_name": {
                            "$trim": {
                                "input": {
                                    "$concat": [
                                        {"$ifNull": ["$profile.first_name", ""]},
                                        " ",
                                        {"$ifNull": ["$profile.last_name", ""]}
                                    ]
                                }
                            }
                        }
                    }
                })
            else:
                match_stage: Dict[str, Any] = {
                    "$expr": {
                        "$in": [
                            {"$concat": ["$profile.first_name", " ", "$profile.last_name"]},
                            driver_names
                        ]
                    }
                }
                if sub_tenant_id:
                    match_stage["sub_tenant_id"] = sub_tenant_id

                pipeline = [
                    {"$match": match_stage},
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
            print(f"SubTenantId: {sub_tenant_id}")
            print(f"AllDriversRequested: {all_drivers_requested}")
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

            driver_ids = self._unique_strings([r["driver_id"] for r in results])
            
            return {
                "success": True,
                "count": len(results),
                "drivers": results,
                "driver_ids": driver_ids
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
