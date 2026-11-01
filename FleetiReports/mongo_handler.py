"""
MongoDB Handler for Fleet Analytics Chatbot
Executes MongoDB queries to fetch asset and driver information
"""

from typing import List, Dict, Any
import logging
import re
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from .config import settings

logger = logging.getLogger(__name__)


def print(*args: Any, **kwargs: Any) -> None:
    logger.debug(" ".join(str(arg) for arg in args))


def _active_asset_match() -> Dict[str, Any]:
    """Active-vehicle conditions (mirrors FleetiQueryRunner.execute._active_asset_filter —
    keep the two in sync).

    A vehicle is ACTIVE only when ALL of these hold together: it is assigned to a device
    AND its status is "Active" or "Maintenance" AND it has a real (non-blank) device IMEI
    AND it has a non-null expiry_date in the future. Anything else is inactive — including a
    vehicle with NO expiry_date or NO device IMEI. Matches the portal's active-assets query
    exactly (same case-sensitive status values) so counts agree with the dashboard.
    Kept as a flat dict (status via $in) so callers can spread it into a larger $match."""
    now = datetime.now(timezone.utc)
    return {
        "device_availability": "AssignedToDevice",
        "status": {"$in": ["Active", "Maintenance"]},
        "device_details.imei": {"$exists": True, "$ne": None, "$not": {"$regex": r"^\s*$"}},
        "expiry_date": {"$exists": True, "$ne": None, "$gt": now},
    }


def _ids_preview(ids: List[str], limit: int = 20) -> Any:
    """Compact id list for logs: full when short, truncated with a count otherwise."""
    ids = list(ids or [])
    if len(ids) <= limit:
        return ids
    return ids[:limit] + [f"...(+{len(ids) - limit} more)"]


class MongoDBHandler:
    """Handles MongoDB operations"""
    
    def __init__(self):
        """Initialize MongoDB client"""
        self.client = MongoClient(settings.MONGO_URI)

    def _normalize_plate(self, plate: str) -> str:
        """Normalize a plate the SAME way the DB does: strip only separators
        (space/-/_) and uppercase. Non-ASCII letters (e.g. Arabic) are KEPT, so
        plates like '7850 ل ط ا' normalize to '7850لطا' and match the stored value."""
        if not plate:
            return ""
        return re.sub(r"[\s\-_]", "", plate).upper()

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

            # Split on separators only (keep non-ASCII tokens like Arabic letters).
            tokens = [t.upper() for t in re.split(r"[\s\-_]+", plate.strip()) if t]
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
                match_stage: Dict[str, Any] = _active_asset_match()
                if sub_tenant_id:
                    match_stage["sub_tenant_id"] = sub_tenant_id

                pipeline = [{"$match": match_stage}]
                pipeline.append({
                    "$project": {
                        "_id": 1,
                        "plate_number": "$details.plate_number",
                        "imei": "$device_details.imei"
                    }
                })
            else:
                # Execute aggregation query by specific plate values.
                match_stage = {
                    "_normalized_plate": {"$in": normalized_variants},
                    **_active_asset_match(),
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
                            "plate_number": "$details.plate_number",
                            "imei": "$device_details.imei"
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
            asset_imeis = self._unique_strings([r["imei"] for r in results if r.get("imei")])

            logger.info(
                "🔎 resolve assets by PLATE | db=%s | plates=%s | all=%s | normalized=%s | active-only | matched=%d | asset_ids=%s",
                db_name, plate_numbers, all_assets_requested, normalized_variants,
                len(results), _ids_preview(asset_ids),
            )

            return {
                "success": True,
                "count": len(results),
                "assets": results,
                "asset_ids": asset_ids,
                "asset_imeis": asset_imeis
            }

        except PyMongoError as e:
            logger.warning("🔎 resolve assets by PLATE FAILED | plates=%s | %s", plate_numbers, str(e)[:300])
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
                # Keep only group-assigned assets that are ACTIVE vehicles.
                {
                    "$lookup": {
                        "from": "Asset",
                        "let": {"aid": "$assigned_assets.asset_id"},
                        "pipeline": [
                            {"$match": {"$expr": {"$eq": ["$_id", "$$aid"]}, **_active_asset_match()}},
                            {"$project": {"_id": 1, "imei": "$device_details.imei"}},
                        ],
                        "as": "_active_asset",
                    }
                },
                {"$match": {"_active_asset.0": {"$exists": True}}},
                {
                    "$project": {
                        "_id": 0,
                        "group_id": "$_id",
                        "deviceGroup": "$name",
                        "asset_id": "$assigned_assets.asset_id",
                        "imei": {"$first": "$_active_asset.imei"}
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
            asset_imeis = self._unique_strings([r["imei"] for r in results if r.get("imei")])
            group_ids = self._unique_strings([r["group_id"] for r in results if r.get("group_id") is not None])

            logger.info(
                "🔎 resolve assets by GROUP | db=%s | groups=%s | all=%s | matched_groups=%d | active-only | matched_assets=%d | asset_ids=%s",
                db_name, group_names, all_groups_requested, len(group_ids), len(results), _ids_preview(asset_ids),
            )

            return {
                "success": True,
                "count": len(results),
                "assets": results,
                "asset_ids": asset_ids,
                "asset_imeis": asset_imeis,
                "group_ids": group_ids
            }

        except PyMongoError as e:
            logger.warning("🔎 resolve assets by GROUP FAILED | groups=%s | %s", group_names, str(e)[:300])
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

            logger.info(
                "🔎 resolve drivers by NAME | db=%s | names=%s | all=%s | matched=%d | driver_ids=%s",
                db_name, driver_names, all_drivers_requested, len(results), _ids_preview(driver_ids),
            )

            return {
                "success": True,
                "count": len(results),
                "drivers": results,
                "driver_ids": driver_ids
            }

        except PyMongoError as e:
            logger.warning("🔎 resolve drivers by NAME FAILED | names=%s | %s", driver_names, str(e)[:300])
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
