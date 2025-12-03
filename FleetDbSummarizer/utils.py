"""
Utility functions for the RAG pipeline
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_json_file(file_path: Path) -> Dict[str, Any]:
    """Load a JSON file and return its contents"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
        return {}


def load_all_collection_files(collection_chunks_dir: Path) -> Dict[str, List[Dict]]:
    """
    Load all JSON files from collection_chunks directory
    Returns a dictionary mapping collection names to their data
    """
    collections = {}

    if not collection_chunks_dir.exists():
        logger.error(f"Collection chunks directory not found: {collection_chunks_dir}")
        return collections

    for collection_dir in collection_chunks_dir.iterdir():
        if collection_dir.is_dir():
            collection_name = collection_dir.name
            collections[collection_name] = []

            for json_file in collection_dir.glob("*.json"):
                subcollection_name = json_file.stem
                data = load_json_file(json_file)

                if data:
                    # Store with subcollection name as key in metadata
                    collections[collection_name].append({
                        'subcollection': subcollection_name,
                        'data': data,
                        'file_path': str(json_file)
                    })

    logger.info(f"Loaded {sum(len(v) for v in collections.values())} files from {len(collections)} collections")
    return collections


def load_collection_schemas(collection_schemas_dir: Path) -> Dict[str, Dict[str, str]]:
    """
    Load all schema files from collection_schemas directory
    Returns a dictionary mapping collection names to their subcollection schemas
    """
    schemas = {}

    if not collection_schemas_dir.exists():
        logger.error(f"Collection schemas directory not found: {collection_schemas_dir}")
        return schemas

    for collection_dir in collection_schemas_dir.iterdir():
        if collection_dir.is_dir():
            collection_name = collection_dir.name
            schemas[collection_name] = {}

            for txt_file in collection_dir.glob("*.txt"):
                subcollection_name = txt_file.stem
                try:
                    with open(txt_file, 'r', encoding='utf-8') as f:
                        schema_content = f.read().strip()
                    schemas[collection_name][subcollection_name] = schema_content
                except Exception as e:
                    logger.error(f"Error loading schema file {txt_file}: {e}")

    logger.info(f"Loaded schemas for {len(schemas)} collections")
    return schemas


def parse_collection_index(md_file: Path) -> Dict[str, Dict[str, Any]]:
    """
    Parse the collection_index_rag.md file to extract collection metadata
    Returns a dictionary mapping collection names to their metadata
    """
    if not md_file.exists():
        logger.warning(f"Collection index file not found: {md_file}")
        return {}
    
    collections_metadata = {}
    
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by collection headers (## CollectionName)
    sections = re.split(r'\n## ', content)
    
    for section in sections[1:]:  # Skip the header
        lines = section.strip().split('\n')
        if not lines:
            continue
        
        collection_name = lines[0].strip()
        
        # Extract description
        description = ""
        use_for = []
        keywords = []
        
        in_description = False
        in_use_for = False
        in_keywords = False
        
        for line in lines[1:]:
            if line.startswith('**Description:**'):
                in_description = True
                description = line.replace('**Description:**', '').strip()
            elif line.startswith('**Use for questions about:**'):
                in_use_for = True
                in_description = False
                in_keywords = False
            elif line.startswith('**Key Keywords:**'):
                in_keywords = True
                in_use_for = False
                in_description = False
                keywords_text = line.replace('**Key Keywords:**', '').strip()
                keywords = [k.strip() for k in keywords_text.split(',')]
            elif in_description and line.strip():
                description += " " + line.strip()
            elif in_use_for and line.strip().startswith('-'):
                use_for.append(line.strip()[1:].strip())
            elif in_keywords and line.strip().startswith('-'):
                keywords_text = line.strip()[1:].strip()
                keywords.extend([k.strip() for k in keywords_text.split(',')])
        
        collections_metadata[collection_name] = {
            'description': description,
            'use_for': use_for,
            'keywords': keywords
        }
    
    logger.info(f"Parsed metadata for {len(collections_metadata)} collections")
    return collections_metadata


def create_collection_description_chunks(md_file: Path) -> List[Dict[str, Any]]:
    """
    Create chunks based on collection descriptions from collection_index_rag.md
    Each collection (including subcollections treated as collections) gets its own chunk
    Chunks are organized by collection with base collections first
    """
    if not md_file.exists():
        logger.warning(f"Collection index file not found: {md_file}")
        return []
    
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by collection headers (## CollectionName)
    sections = re.split(r'\n## ', content)
    
    chunks = []
    collections_order = {}  # Track collection groups for ordering
    
    for section in sections[1:]:  # Skip the header
        lines = section.strip().split('\n')
        if not lines:
            continue
        
        collection_name = lines[0].strip()
        
        # Extract description, use_for, and keywords
        description = ""
        use_for = []
        keywords = []
        
        in_description = False
        in_use_for = False
        in_keywords = False
        
        for line in lines[1:]:
            if line.startswith('**Description:**'):
                in_description = True
                description = line.replace('**Description:**', '').strip()
            elif line.startswith('**Use for questions about:**'):
                in_use_for = True
                in_description = False
                in_keywords = False
            elif line.startswith('**Key Keywords:**'):
                in_keywords = True
                in_use_for = False
                in_description = False
                keywords_text = line.replace('**Key Keywords:**', '').strip()
                keywords = [k.strip() for k in keywords_text.split(',')]
            elif in_description and line.strip() and not line.startswith('**'):
                description += " " + line.strip()
            elif in_use_for and line.strip().startswith('-'):
                use_for.append(line.strip()[1:].strip())
            elif in_keywords and line.strip().startswith('-'):
                keywords_text = line.strip()[1:].strip()
                keywords.extend([k.strip() for k in keywords_text.split(',')])
        
        # Create chunk text from description, use cases, and keywords
        chunk_text_parts = [
            f"Collection Name: {collection_name}",
            f"\nDescription: {description}",
            f"\nUse for questions about:",
            *[f"  - {use_case}" for use_case in use_for],
            f"\nKey Keywords: {', '.join(keywords)}"
        ]
        chunk_text = "\n".join(chunk_text_parts)
        
        # Determine collection group (e.g., "Asset" from "asset_details_base")
        # All subcollections are treated as independent collections
        collection_group = collection_name.split('_')[0] if '_' in collection_name else collection_name
        
        # Determine if it's a base collection (ends with "_base" or is just the collection name)
        is_base = collection_name.endswith('_base') or '_' not in collection_name
        
        # Store chunk
        chunk = {
            'text': chunk_text,
            'collection_name': collection_name,
            'collection_group': collection_group,
            'is_base': is_base,
            'description': description,
            'use_for': use_for,
            'keywords': keywords
        }
        
        # Track collections for ordering
        if collection_group not in collections_order:
            collections_order[collection_group] = {'base': [], 'others': []}
        
        if is_base:
            collections_order[collection_group]['base'].append(chunk)
        else:
            collections_order[collection_group]['others'].append(chunk)
    
    # Organize chunks: base collections first, then others, grouped by collection
    ordered_chunks = []
    for collection_group in sorted(collections_order.keys()):
        # Add base collections first
        ordered_chunks.extend(collections_order[collection_group]['base'])
        # Then add other collections in the same group
        ordered_chunks.extend(collections_order[collection_group]['others'])
    
    logger.info(f"Created {len(ordered_chunks)} collection description chunks")
    return ordered_chunks


def format_json_for_chunking(data: Dict[str, Any], collection_name: str, subcollection_name: str) -> str:
    """
    Format JSON data into a text string suitable for chunking
    """
    # Convert JSON to a readable text format
    lines = [f"Collection: {collection_name}", f"Subcollection: {subcollection_name}"]
    
    def format_value(key: str, value: Any, indent: int = 0) -> List[str]:
        """Recursively format JSON values"""
        result = []
        prefix = "  " * indent
        
        if isinstance(value, dict):
            result.append(f"{prefix}{key}:")
            for k, v in value.items():
                result.extend(format_value(k, v, indent + 1))
        elif isinstance(value, list):
            result.append(f"{prefix}{key}: [list with {len(value)} items]")
            if value and isinstance(value[0], dict):
                for i, item in enumerate(value[:5]):  # Limit to first 5 items
                    result.append(f"{prefix}  Item {i+1}:")
                    for k, v in item.items():
                        result.extend(format_value(k, v, indent + 2))
        else:
            result.append(f"{prefix}{key}: {value}")
        
        return result
    
    for key, value in data.items():
        lines.extend(format_value(key, value))
    
    return "\n".join(lines)


def hierarchical_chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> List[Dict[str, Any]]:
    """
    Hierarchical chunking: first by paragraphs (\n\n), then by sentences
    Returns list of chunks with metadata
    """
    chunks = []
    
    # First level: split by double newlines (paragraphs)
    paragraphs = text.split('\n\n')
    
    current_chunk = ""
    chunk_id = 0
    
    for para in paragraphs:
        # If adding this paragraph would exceed chunk size, save current chunk
        if len(current_chunk) + len(para) > chunk_size and current_chunk:
            chunks.append({
                'text': current_chunk.strip(),
                'chunk_id': chunk_id,
                'size': len(current_chunk),
                'type': 'paragraph'
            })
            chunk_id += 1
            # Start new chunk with overlap
            if overlap > 0:
                words = current_chunk.split()
                overlap_text = ' '.join(words[-overlap:]) if len(words) > overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para
        else:
            current_chunk += "\n\n" + para if current_chunk else para
    
    # Add final chunk
    if current_chunk.strip():
        chunks.append({
            'text': current_chunk.strip(),
            'chunk_id': chunk_id,
            'size': len(current_chunk),
            'type': 'paragraph'
        })
    
    # Second level: if any chunk is still too large, split by sentences
    final_chunks = []
    for chunk in chunks:
        if len(chunk['text']) > chunk_size:
            # Split by sentences
            sentences = re.split(r'(?<=[.!?])\s+', chunk['text'])
            current_sent_chunk = ""
            sent_chunk_id = 0
            
            for sent in sentences:
                if len(current_sent_chunk) + len(sent) > chunk_size and current_sent_chunk:
                    final_chunks.append({
                        'text': current_sent_chunk.strip(),
                        'chunk_id': f"{chunk['chunk_id']}_{sent_chunk_id}",
                        'size': len(current_sent_chunk),
                        'type': 'sentence',
                        'parent_id': chunk['chunk_id']
                    })
                    sent_chunk_id += 1
                    # Overlap
                    if overlap > 0:
                        words = current_sent_chunk.split()
                        overlap_text = ' '.join(words[-overlap:]) if len(words) > overlap else current_sent_chunk
                        current_sent_chunk = overlap_text + " " + sent
                    else:
                        current_sent_chunk = sent
                else:
                    current_sent_chunk += " " + sent if current_sent_chunk else sent
            
            if current_sent_chunk.strip():
                final_chunks.append({
                    'text': current_sent_chunk.strip(),
                    'chunk_id': f"{chunk['chunk_id']}_{sent_chunk_id}",
                    'size': len(current_sent_chunk),
                    'type': 'sentence',
                    'parent_id': chunk['chunk_id']
                })
        else:
            final_chunks.append(chunk)
    
    return final_chunks


def get_parent_collection_and_base(subcollection_name: str) -> Tuple[str, str]:
    """
    Get parent collection name and base collection name from a subcollection name
    
    Examples:
    - "asset_details_base" -> ("Asset", "asset_base")
    - "asset_base" -> ("Asset", "asset_base")
    - "AvlRecord_base" -> ("AvlRecord", "AvlRecord_base")
    - "Driver_license" -> ("Driver", "Driver_base")
    """
    # Normalize the name
    name = subcollection_name.strip()
    
    # Determine parent collection (capitalize first part)
    if '_' in name:
        parent = name.split('_')[0].capitalize()
        # Handle special cases like "asset_details_base" -> "Asset"
        if parent.lower() == 'asset' and 'details' in name.lower():
            parent = "Asset"
        elif parent.lower() == 'driver':
            parent = "Driver"
        elif parent.lower() == 'alertrule':
            parent = "AlertRule"
        elif parent.lower() == 'alerthistory':
            parent = "AlertHistory"
        elif parent.lower() == 'avlrecord':
            parent = "AvlRecord"
        elif parent.lower() == 'trip':
            parent = "Trip"
        elif parent.lower() == 'device':
            parent = "Device"
        elif parent.lower() == 'events':
            parent = "Events"
        elif parent.lower() == 'geofence':
            parent = "Geofence"
        elif parent.lower() == 'systemalertrule':
            parent = "SystemAlertRule"
        elif parent.lower() == 'dailyanalytics':
            parent = "DailyAnalytics"
    else:
        parent = name.capitalize()
    
    # Determine base collection name
    if name.endswith('_base'):
        base = name  # Already base
    elif 'asset' in name.lower():
        base = "asset_base"
    elif name.startswith('Driver') or name.startswith('driver'):
        base = "Driver_base"
    elif name.startswith('AlertRule') or name.startswith('alertrule') or name.startswith('Alert_Rule'):
        base = "AlertRule_base"
    elif name.startswith('AlertHistory') or name.startswith('alerthistory'):
        base = "AlertHistory_base"
    elif name.startswith('AvlRecord') or name.startswith('avlrecord'):
        base = "AvlRecord_base"
    elif name.startswith('Trip') or name.startswith('trip'):
        base = "Trip_base"
    elif name.startswith('Device') or name.startswith('device'):
        base = "Device_base"
    elif name.startswith('Events') or name.startswith('events'):
        base = "Events_base"
    elif name.startswith('Geofence') or name.startswith('geofence'):
        base = "Geofence_base"
    elif name.startswith('SystemAlertRule') or name.startswith('systemalertrule'):
        base = "SystemAlertRule_base"
    elif name.startswith('DailyAnalytics') or name.startswith('dailyanalytics'):
        base = "DailyAnalytics_base"
    else:
        base = f"{parent.lower()}_base"
    
    return parent, base


def get_immediate_parent_base(subcollection_name: str) -> str:
    """
    Get the immediate parent base collection for a given subcollection.
    Returns empty string if the subcollection is already the ultimate base.
    
    Examples:
    - "asset_details_cargo_load_management" -> "asset_details_base"
    - "asset_details_base" -> "asset_base"
    - "asset_base" -> "" (ultimate base, no parent)
    - "Driver_license" -> "Driver_base"
    - "Driver_base" -> "" (ultimate base, no parent)
    """
    name = subcollection_name.strip()
    
    # Define all ultimate bases
    ultimate_bases = [
        "asset_base", "Driver_base", "AlertRule_base", "AlertHistory_base",
        "AvlRecord_base", "Trip_base", "Device_base", "Events_base",
        "Geofence_base", "SystemAlertRule_base", "DailyAnalytics_base"
    ]
    
    # If it's already the ultimate base, no parent
    if name in ultimate_bases:
        return ""
    
    # Asset hierarchy: asset_details_* -> asset_details_base -> asset_base
    if name.startswith("asset_details_") and not name.endswith("_base"):
        # e.g., "asset_details_cargo_load_management" -> "asset_details_base"
        return "asset_details_base"
    elif name == "asset_details_base":
        # "asset_details_base" -> "asset_base"
        return "asset_base"
    
    # For other collections, find the parent base
    parent, base = get_parent_collection_and_base(name)
    
    # If the current name is the base itself, return empty (ultimate base)
    if name == base:
        return ""
    
    # Otherwise, return the base as the immediate parent
    return base


def get_all_parent_bases(subcollection_name: str) -> List[str]:
    """
    Recursively get all parent base collections for a given subcollection.
    Returns a list of parent bases in order from immediate to ultimate.
    
    Examples:
    - "asset_details_cargo_load_management" -> ["asset_details_base", "asset_base"]
    - "asset_details_base" -> ["asset_base"]
    - "asset_base" -> [] (ultimate base, no parents)
    - "Driver_license" -> ["Driver_base"]
    - "Driver_base" -> [] (ultimate base, no parents)
    """
    parent_bases = []
    current = subcollection_name.strip()
    
    while True:
        parent_base = get_immediate_parent_base(current)
        if not parent_base:  # Reached ultimate base
            break
        parent_bases.append(parent_base)
        current = parent_base  # Move up the hierarchy
    
    return parent_bases


def replace_values_with_types(data: Any, parent_type: str = None) -> Any:
    """
    Recursively replace JSON values with their types
    
    Examples:
    - "hello" -> ""
    - 123 -> "int"
    - 123.45 -> "float"
    - true -> "bool"
    - {"key": "value"} -> {"key": ""}
    - [123, 456] -> ["int"]
    - [31.17, 74.08] -> ["float", "float"] (for arrays with multiple elements, show each)
    - {"$date": "2025-10-09T12:29:00.409Z"} -> {"$date": ""}
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key == "$date":
                result[key] = ""  # Special case for date
            else:
                result[key] = replace_values_with_types(value)
        return result
    elif isinstance(data, list):
        if len(data) == 0:
            return []
        # For arrays, determine type from elements
        element_types = set()
        for item in data[:10]:  # Sample first 10 elements
            item_type = type(item).__name__
            element_types.add(item_type)
        
        # If all same type
        if len(element_types) == 1:
            element_type = list(element_types)[0]
            if element_type == 'dict':
                # For dict arrays, process first dict
                return [replace_values_with_types(data[0])] if len(data) > 0 else []
            elif element_type == 'int':
                # For coordinate arrays, show type for each position if small array (2 elements typical for coordinates)
                if len(data) <= 2:
                    return [element_type for _ in data]  # ["int", "int"]
                return [element_type]  # ["int"]
            elif element_type == 'float':
                # For coordinate arrays like [31.36, 74.23], show ["float", "float"]
                if len(data) <= 2:
                    return [element_type for _ in data]  # ["float", "float"]
                return [element_type]  # ["float"]
            elif element_type == 'str':
                return [element_type]  # ["str"]
            elif element_type == 'bool':
                return [element_type]  # ["bool"]
            elif element_type == 'NoneType':
                return [None]
            else:
                return [element_type]
        else:
            # Mixed types - use first type or process as list of dicts
            first_type = type(data[0]).__name__
            if first_type == 'dict':
                return [replace_values_with_types(data[0])]
            return [first_type]
    elif isinstance(data, str):
        return ""
    elif isinstance(data, bool):
        return "bool"
    elif isinstance(data, int):
        return "int"
    elif isinstance(data, float):
        return "float"
    elif data is None:
        return None  # Keep None as None for null values
    else:
        return type(data).__name__


def generate_relationship_rules(selected_collections: List[str]) -> List[str]:
    """
    Generate relationship rules between selected collections
    
    Args:
        selected_collections: List of collection names (e.g., ["Asset", "Trip", "Events"])
    
    Returns:
        List of relationship rule strings
    """
    # Define relationship mappings (collection1 -> collection2: description)
    relationships = {
        ("Asset", "Trip"): "The relation between the Asset and the Trips collection is one to many. For each asset there may be many trips. Trip.driver_info.asset_id = Asset.id",
        ("Asset", "Events"): "The relation between the Asset and the Events collection is one to many. For each asset there may be many events. Events.device_context.asset_id = Asset.id",
        ("Asset", "AlertHistory"): "The relation between the Asset and the AlertHistory collection is one to many. For each asset there may be many alert history records. AlertHistory.asset_info._id = Asset.id",
        ("Asset", "AvlRecord"): "The relation between the Asset and the AvlRecord collection is one to many. For each asset there may be many AVL records. AvlRecord.device_context.asset_id = Asset.id",
        ("Asset", "Geofence"): "The relation between the Asset and the Geofence collection is many to many. Assets can be assigned to multiple geofences, and geofences can contain multiple assets.",
        ("Asset", "Device"): "The relation between the Asset and the Device collection is one to many. For each asset there may be many devices. Device.asset_id = Asset.id & Device.imei = Asset.imei",
        ("Asset", "Driver"): "The relation between the Asset and the Driver collection is many to many. Drivers can be assigned to multiple assets, and assets can be assigned to multiple drivers. Driver.asset_assignments._id = Asset.id",
        ("Asset", "DailyAnalytics"): "The relation between the Asset and the DailyAnalytics collection is one to many. For each asset there may be many daily analytics records. DailyAnalytics.asset_id = Asset.id",
        
        ("Driver", "Trip"): "The relation between the Driver and the Trips collection is one to many. For each driver there may be many trips. Trip.driver_info.driver_info.id = Driver.id",
        ("Driver", "Events"): "The relation between the Driver and the Events collection is one to many. For each driver there may be many events. Events.device_context.driver_info.id = Driver.id",
        ("Driver", "AvlRecord"): "The relation between the Driver and the AvlRecord collection is one to many. For each driver there may be many AVL records. AvlRecord.device_context.driver_info.id = Driver.id",
        ("Driver", "DailyAnalytics"): "The relation between the Driver and the DailyAnalytics collection is one to many. For each driver there may be many daily analytics records. DailyAnalytics.driver_id = Driver.id",
        
        ("Trip", "Device"): "The relation between the Trip and the Device collection is one to many. For each trip there may be many devices. Device.imei = Trip.imei",
        
        ("Geofence", "Asset"): "The relation between the Geofence and the Asset collection is many to many. Geofences can contain multiple assets, and assets can be assigned to multiple geofences. Geofence.asset_assignments.asset_id = Asset.id",
        ("Geofence", "AlertHistory"): "The relation between the Geofence and the AlertHistory collection is one to many. For each geofence there may be many geofence event records in AlertHistory. AlertHistory.alert_info.alert_rule_id = Geofence.id",
        
        ("AlertRule", "AlertHistory"): "The relation between the AlertRule and the AlertHistory collection is one to many. For each alert rule there may be many alert history records when the rule is triggered. AlertHistory.alert_info.alert_rule_id = AlertRule.id",
        
        ("SystemAlertRule", "Events"): "The relation between the SystemAlertRule and the Events collection is one to many. For each system alert rule there may be many event records when the rule is triggered. Events.event_type = SystemAlertRule.event_type",
        
        ("Device", "AvlRecord"): "The relation between the Device and the AvlRecord collection is one to many. For each device there may be many AVL records. Device.imei = AvlRecord.imei & Device.id = AvlRecord.device_id",
    }
    
    rules = []
    # Generate rules for all pairs of selected collections
    for i, col1 in enumerate(selected_collections):
        for col2 in selected_collections[i+1:]:
            # Check both directions (col1->col2 and col2->col1)
            if (col1, col2) in relationships:
                rules.append(relationships[(col1, col2)])
            elif (col2, col1) in relationships:
                rules.append(relationships[(col2, col1)])
    
    return rules


def build_collection_json(
    user_question: str,
    selected_collections: List[str],
    collection_schemas_dir: Path
) -> Dict[str, Any]:
    """
    Build JSON structure based on selected collections using schema files

    Args:
        user_question: The user's question
        selected_collections: List of collection names from LLM (e.g., ["asset_details_base", "AvlRecord_base"])
        collection_schemas_dir: Path to collection_schemas directory

    Returns:
        JSON structure with collection data containing schema text
    """
    # Step 1: Map subcollections to parent collections and add base collections recursively
    parent_to_subcollections = {}
    selected_subcollections_set = set()

    for selected in selected_collections:
        selected = selected.strip().strip('"\'')
        if not selected:
            continue

        parent, _ = get_parent_collection_and_base(selected)

        # Initialize parent collection
        if parent not in parent_to_subcollections:
            parent_to_subcollections[parent] = set()

        # Add the selected subcollection
        parent_to_subcollections[parent].add(selected)
        selected_subcollections_set.add(selected)

        # Special handling for Driver collection: always include Driver_base and Driver_Profile
        if parent == "Driver" and selected != "Driver_base" and selected != "Driver_Profile":
            # Add Driver_base if not already selected
            if "Driver_base" not in selected_subcollections_set:
                parent_to_subcollections[parent].add("Driver_base")
                selected_subcollections_set.add("Driver_base")
            # Add Driver_Profile if not already selected
            if "Driver_Profile" not in selected_subcollections_set:
                parent_to_subcollections[parent].add("Driver_Profile")
                selected_subcollections_set.add("Driver_Profile")

        # Recursively get all parent bases and add them
        parent_bases = get_all_parent_bases(selected)
        for parent_base in parent_bases:
            if parent_base not in selected_subcollections_set:
                # Get the parent collection for the parent base
                parent_collection, _ = get_parent_collection_and_base(parent_base)
                if parent_collection not in parent_to_subcollections:
                    parent_to_subcollections[parent_collection] = set()
                parent_to_subcollections[parent_collection].add(parent_base)
                selected_subcollections_set.add(parent_base)

    # Step 2: Load schema files from collection_schemas folder
    collection_data = {}
    all_schemas = load_collection_schemas(collection_schemas_dir)

    for parent_collection, subcollections in parent_to_subcollections.items():
        if parent_collection not in all_schemas:
            logger.warning(f"No schemas found for collection: {parent_collection}")
            continue

        selected_subs = []
        all_fields = []

        # Sort subcollections: base first, then others
        sorted_subs = sorted(subcollections, key=lambda x: (not x.endswith('_base'), x))

        # Load each selected subcollection schema and extract fields
        for subcollection_name in sorted_subs:
            if subcollection_name in all_schemas[parent_collection]:
                selected_subs.append(subcollection_name)
                schema_text = all_schemas[parent_collection][subcollection_name]
                
                # Extract fields from schema text (remove "Collection: X\nFields:\n" header)
                lines = schema_text.strip().split('\n')
                fields_started = False
                for line in lines:
                    line = line.strip()
                    if line.startswith('Fields:'):
                        fields_started = True
                        continue
                    if fields_started and line.startswith('- '):
                        # This is a field line
                        if line not in all_fields:  # Avoid duplicates
                            all_fields.append(line)
                    elif fields_started and line and not line.startswith('Collection:'):
                        # Handle any non-field content after Fields: (shouldn't happen, but just in case)
                        continue
            else:
                logger.warning(f"Schema not found for subcollection: {subcollection_name}")

        if selected_subs:
            # Combine all fields into a single schema with one collection header
            combined_schema = f"Collection: {parent_collection}\nFields:\n" + "\n".join(all_fields)
            collection_data[parent_collection] = {
                "selected_sub_collections": sorted(selected_subs),
                "schema": combined_schema
            }

    # Step 3: Generate relationship rules between selected collections
    relationship_rules = generate_relationship_rules(sorted(parent_to_subcollections.keys()))

    # Step 4: Build final JSON structure
    result = {
        "user_question": user_question,
        "selected_collections": sorted(parent_to_subcollections.keys()),
        "collection_data": collection_data,
        "rules": relationship_rules
    }

    return result


def create_parent_chunks(small_chunks: List[Dict[str, Any]], parent_size: int = 2048) -> Dict[str, str]:
    """
    Create parent chunks from small chunks (Small-to-Big retrieval)
    Returns a mapping of chunk_id to parent chunk text
    """
    parent_chunks = {}
    
    # Group chunks by their parent_id (if they have one)
    parent_groups = {}
    standalone_chunks = []
    
    for chunk in small_chunks:
        if 'parent_id' in chunk:
            parent_id = chunk['parent_id']
            if parent_id not in parent_groups:
                parent_groups[parent_id] = []
            parent_groups[parent_id].append(chunk)
        else:
            standalone_chunks.append(chunk)
    
    # Create parent chunks from groups
    for parent_id, child_chunks in parent_groups.items():
        parent_text = "\n\n".join([c['text'] for c in child_chunks])
        if len(parent_text) <= parent_size:
            parent_chunks[parent_id] = parent_text
        else:
            # If too large, use first part
            parent_text = parent_text[:parent_size]
            parent_chunks[parent_id] = parent_text
    
    # For standalone chunks, use themselves as parents
    for chunk in standalone_chunks:
        parent_chunks[chunk['chunk_id']] = chunk['text']
    
    return parent_chunks

