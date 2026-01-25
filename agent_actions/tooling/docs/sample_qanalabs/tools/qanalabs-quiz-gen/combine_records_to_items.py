import json
from agent_actions import udf_tool

def _dedup_preserve_order(seq):
    """
    Works for strings AND dicts.
    Dicts are deduped by JSON canonicalization (sorted keys).
    """
    seen = set()
    out = []
    for x in seq:
        if x is None:
            continue
        if isinstance(x, dict):
            key = json.dumps(x, sort_keys=True, ensure_ascii=False)
        else:
            key = x
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out

@udf_tool()
def combine_records_to_items(records):
    """
    Group by (cluster_id, id).
    Keep outer fields from the first item in each group.
    In content: flagged_items[], cluster_id, url[] (note singular key name).
    """
    groups = {}

    for rec in records:
        c = rec.get("content") or {}
        key = (c.get("cluster_id"), c.get("id"))

        if key not in groups:
            groups[key] = {
                "base": {
                    "source_guid": rec.get("source_guid"),
                    "content": {},  # to be filled
                    "target_id": rec.get("target_id"),
                    "node_id": rec.get("node_id"),
                    "lineage": rec.get("lineage"),
                },
                "cluster_id": c.get("cluster_id"),
                "url": [],
                "page_content": c.get("page_content"),
                "bloom_details": c.get("bloom_details"),
                "platform_name": c.get("platform_name"),
                "exam_name": c.get("exam_name"),
                "flagged_items": [],
            }

        g = groups[key]

        # Collect one item payload from this record's content
        item = {
            "fact": c.get("fact"),
            "quote": c.get("quote"),
            "technical_level": c.get("technical_level"),
            "cluster_tag": c.get("cluster_tag")
        }
        # Only keep if it has at least one non-empty field
        if any(v for v in item.values()):
            g["flagged_items"].append(item)

        if c.get("url"):
            g["url"].append(c["url"])

    # Build final list
    merged = []
    for g in groups.values():
        base = g["base"]
        base["content"] = {
            "flagged_items": _dedup_preserve_order(g["flagged_items"]),
            "cluster_id": g["cluster_id"],
            "page_content": g["page_content"],
            "platform_name": g["platform_name"],
            "exam_name": g["exam_name"],
            "bloom_details": g["bloom_details"],
            "url": _dedup_preserve_order(g["url"]),  # singular key, array value
        }
        merged.append(base)

    return merged





def needs_split(cluster_validation_result):
    """
    Returns True if the cluster should be split into new clusters.
    """
    return not cluster_validation_result.get("should_keep_cluster", True)


@udf_tool()
def create_new_clusters(data):
    """
    Groups flagged items into new clusters based on the `new_clusters` mapping,
    and assigns the `new_clusterN` keys as the new `cluster_id` values.

    Returns a list of cluster payloads, each structured like:
    {
        "flagged_items": [...],
        "cluster_id": "new_clusterN",
        "url": [...]
    }
    """
    # Handle content wrapper
    if 'content' in data:
        cluster_validation_result = data['content']
    else:
        cluster_validation_result = data

    flagged_items = cluster_validation_result.get("flagged_items", [])
    reasoning = cluster_validation_result.get("reasoning", [])
    page_content = cluster_validation_result.get("page_content", [])
    bloom_details = cluster_validation_result.get("bloom_details", [])
    platform_name = cluster_validation_result.get("platform_name", [])
    exam_name = cluster_validation_result.get("exam_name", [])
    cluster_mapping = cluster_validation_result.get("new_clusters", {})
    urls = cluster_validation_result.get("url", [])

    # Build lookup: cluster_tag -> full item
    tag_to_item = {item["cluster_tag"]: item for item in flagged_items}

    # Build new cluster payloads with new_clusterN as cluster_id
    new_cluster_payloads = []

    for new_cluster_id, cluster_tags in cluster_mapping.items():
        new_payload = {
            "flagged_items": [
                tag_to_item[tag] for tag in cluster_tags if tag in tag_to_item
            ],
            "cluster_id": new_cluster_id,
            "should_keep_cluster": False,
            "reasoning": reasoning,
            "page_content": page_content,
            "bloom_details": bloom_details,
            "exam_name": exam_name,
            "platform_name": platform_name,
            "url": urls
        }
        new_cluster_payloads.append(new_payload)

    return new_cluster_payloads




