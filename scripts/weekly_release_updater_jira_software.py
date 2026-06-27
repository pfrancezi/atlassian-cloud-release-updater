#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
weekly_release_updater_jira_software.py

Marketplace-ready customer-run utility for Atlassian release update tracking.

Sources used by this script:
1. Atlassian Admin private release-management API, optional and customer-run.
2. Atlassian Community Release Notes public API.

No Forge app, Connect app, external backend, or hosted service is required.
The script is intended to be run by the customer in their own environment.
The vendor does not receive, transmit, or store Atlassian credentials, API tokens,
session cookies, or customer data.

Date field mode for this file: jira_software
- jpd: date fields are sent as Jira Product Discovery date-range strings,
       for example {"start":"2026-06-22","end":"2026-06-22"}.
- jira_software: date fields are sent as plain Jira dates, for example 2026-06-22.
"""

import getpass
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests

# =============================================================================
# CONFIGURATION
# =============================================================================
# Keep these defaults empty if this repository is public.
# You can fill them locally, or use environment variables instead.
# Example environment variables are listed in env.example.

DATE_FIELD_MODE = "jira_software"

DEFAULT_ORG_ID = ""
DEFAULT_JIRA_BASE_URL = ""
DEFAULT_JIRA_PROJECT_KEY = ""
DEFAULT_JIRA_ISSUE_TYPE = ""
DEFAULT_JIRA_EMAIL = ""
DEFAULT_ACTIONS_OUTPUT = f"weekly_release_update_actions_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

PRIVATE_PAGE_LIMIT = 40
COMMUNITY_PAGE_LIMIT = 100

NEW_THIS_WEEK_VALUE = "NEW THIS WEEK"

SOURCE_PRIVATE = "Private"
SOURCE_COMMUNITY = "Community"

SOURCE_REQUEST_TIMEOUT_SECONDS = 120
SOURCE_REQUEST_CONNECT_TIMEOUT_SECONDS = 15
SOURCE_REQUEST_MAX_RETRIES = 3
SOURCE_REQUEST_RETRY_SLEEP_SECONDS = 5

AUTO_CREATE_FIELD_OPTIONS = True
UPDATE_DESCRIPTION_ON_SOURCE_ADDED = True
CREATE_MISSING_ISSUES_DEFAULT = True

# Public Community Release Notes API.
COMMUNITY_API_URL = "https://community.atlassian.com/gateway/api/public/app-updates/v1/changes"
COMMUNITY_DETAIL_URL_TEMPLATE = "https://community.atlassian.com/gateway/api/public/app-updates/v1/change-details/{change_id}"
COMMUNITY_LEGACY_DETAIL_URL_TEMPLATE = "https://community.atlassian.com/gateway/api/public/app-updates/v1/changes/{change_id}"

# =============================================================================
# JIRA CUSTOM FIELD IDS
# =============================================================================
# Replace these values with the custom field IDs from your Jira project.
# Leave optional fields empty ("") to skip them.
# Example: CF_SOURCE = "customfield_13005"

CF_CHANGEKEY = ""                    # Short text, optional. Public provider key, when available.
CF_ADMIN_ID = ""                     # Short text, recommended. Atlassian Admin/Community opaque change id.
CF_PRODUCTS = ""                     # Multi-select, recommended. Technical product tags.
CF_SOURCE = ""                       # Multi-select, recommended. Values: Private, Community.
CF_CHANGE_TYPE = ""                  # Single-select, optional. Private/Admin change type.
CF_CHANGE_STATUS = ""                # Single-select, recommended. Private/Admin lifecycle status.
CF_SITE_STATUS = ""                  # Single-select, optional. Private/Admin site release status.
CF_POSTDATE = ""                     # Date, optional. Private/Admin post date.
CF_RELEASE_START = ""                # Date or JPD date range, optional. Private/Admin release start.
CF_RELEASE_END = ""                  # Date or JPD date range, optional. Private/Admin release end.
CF_IS_DELAYABLE = ""                 # Multi-select Yes/No, optional.
CF_IS_DELAYED = ""                   # Multi-select Yes/No, optional.
CF_COMMUNITY_STATUS = ""             # Single-select, recommended. Community lifecycle status.
CF_COMMUNITY_CHANGE_TYPE = ""        # Multi-select, recommended. Community change type.
CF_COMMUNITY_RELEASE_START = ""      # Date or JPD date range, recommended.
CF_COMMUNITY_FIRST_PUBLISHED = ""    # Date or JPD date range, recommended.
CF_COMMUNITY_WEEK_START = ""         # Date or JPD date range, recommended. Monday of first-published week.
CF_COMMUNITY_WEEK_END = ""           # Date or JPD date range, recommended. Sunday of first-published week.

# If your select-list fields already have contexts and option creation fails,
# set AUTO_CREATE_FIELD_OPTIONS = False and create the options manually.
FIELD_CONTEXT_IDS: Dict[str, Optional[str]] = {}

# =============================================================================
# PRODUCT MAPPING
# =============================================================================

PRODUCT_ALIAS_EXPANSIONS = {
    "mercury": ["focus"],
    "radar": ["talent"],
}

COMMUNITY_PRODUCT_TO_TECH_PRODUCTS = {
    "cloud-admin": ["cloud-admin"],
    "admin": ["cloud-admin"],
    "administration": ["cloud-admin"],
    "jira-software": ["jira-software"],
    "jira": ["jira-software"],
    "jsw": ["jira-software"],
    "jira-servicedesk": ["jira-servicedesk"],
    "jira-service-management": ["jira-servicedesk"],
    "jira-customer-service": ["jira-servicedesk"],
    "customer-service-management": ["jira-servicedesk"],
    "opsgenie": ["jira-servicedesk"],
    "jira-product-discovery": ["jira-product-discovery"],
    "jpd": ["jira-product-discovery"],
    "confluence": ["confluence"],
    "bitbucket": ["bitbucket"],
    "compass": ["compass"],
    "rovo": ["rovo"],
    "loom": ["loom"],
    "assets": ["assets"],
    "cmdb": ["assets"],
    "mercury": ["mercury", "focus"],
    "focus": ["mercury", "focus"],
    "radar": ["radar", "talent"],
    "talent": ["radar", "talent"],
    "studio": ["studio"],
    "goal": ["goal"],
    "goals": ["goal"],
    "project": ["project"],
    "projects": ["project"],
    "teams": ["teams"],
    "atlas": ["atlas"],
    "home": ["home"],
    "analytics": ["analytics"],
}

FD_STRICT_PATTERN = re.compile(r"^FD-\d+$")

# =============================================================================
# GENERIC HELPERS
# =============================================================================


def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_text_key(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def normalize_value_for_compare(value: Any) -> str:
    return normalize_text_key(value).upper()


def is_fd_change_key(value: Any) -> bool:
    return bool(isinstance(value, str) and FD_STRICT_PATTERN.match(value.strip()))


def configured(field_id: str) -> bool:
    return bool(str(field_id or "").strip())


def field_value(fields: Dict[str, Any], field_id: str) -> Any:
    if not configured(field_id):
        return None
    return fields.get(field_id)


def to_option(value: Optional[str]) -> Optional[Dict[str, str]]:
    if not value:
        return None
    return {"value": str(value)}


def to_multi_options(values: Iterable[str]) -> List[Dict[str, str]]:
    cleaned = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append({"value": text})
    return cleaned


def normalize_single_option_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("value") or value.get("name")
    if isinstance(value, str):
        return value.strip() or None
    return str(value).strip() or None


def normalize_multi_option_values(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            option_value = normalize_single_option_value(item)
            if option_value:
                result.append(option_value)
        return result
    option_value = normalize_single_option_value(value)
    return [option_value] if option_value else []


def merge_unique(*values_or_lists: Any) -> List[str]:
    result = []
    seen = set()
    for values in values_or_lists:
        if not values:
            continue
        if not isinstance(values, list):
            values = [values]
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key not in seen:
                seen.add(key)
                result.append(text)
    return result


def sort_normalized_list(values: Iterable[str]) -> List[str]:
    return sorted(normalize_value_for_compare(v) for v in values if str(v or "").strip())


def expand_product_aliases(products: Any) -> List[str]:
    base_products = merge_unique(products)
    expanded = list(base_products)
    seen = {p.lower() for p in expanded}
    for product in list(base_products):
        for extra in PRODUCT_ALIAS_EXPANSIONS.get(product.strip().lower(), []):
            if extra.lower() not in seen:
                seen.add(extra.lower())
                expanded.append(extra)
    return expanded


def normalize_product_key(value: Any) -> str:
    return normalize_text_key(value).replace(" ", "-")


def get_community_technical_products(products: Any) -> List[str]:
    mapped = []
    unmapped = []
    for product in merge_unique(products):
        values = COMMUNITY_PRODUCT_TO_TECH_PRODUCTS.get(normalize_product_key(product))
        if values:
            mapped.extend(values)
        else:
            unmapped.append(product)
    if unmapped:
        print(f"[COMMUNITY] Unmapped product labels: {sorted(set(unmapped))}")
    return expand_product_aliases(mapped)


def normalize_private_status(status: Any) -> Optional[str]:
    if not status:
        return None
    value = str(status).strip().upper().replace(" ", "_")
    mapping = {
        "ROLLING_OUT": "ROLLING_OUT",
        "COMING_SOON": "COMING_SOON",
        "PLANNED": "PLANNED",
        "GENERALLY_AVAILABLE": "GENERALLY_AVAILABLE",
        "GENERAL_AVAILABLE": "GENERALLY_AVAILABLE",
        "ROLLOUT_COMPLETE": "GENERALLY_AVAILABLE",
        "ROLLOUT_COMPLETED": "GENERALLY_AVAILABLE",
        "ROLL_OUT_COMPLETE": "GENERALLY_AVAILABLE",
        "ROLL_OUT_COMPLETED": "GENERALLY_AVAILABLE",
        "EXPERIMENT": "EXPERIMENT",
        "DEPRECATED": "DEPRECATED",
        "ANNOUNCEMENT": "ANNOUNCEMENT",
    }
    return mapping.get(value, value)


def get_admin_id_from_record(record: Dict[str, Any]) -> Optional[str]:
    """Return the opaque Atlassian Admin/Community change id, never FD-* if avoidable."""
    for key in ("adminId", "communityId", "privateId", "id"):
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and not is_fd_change_key(text):
            return text
    return None


def get_change_key(record: Dict[str, Any]) -> str:
    change_key = record.get("changeKey") or record.get("change_key")
    if isinstance(change_key, str) and change_key.strip():
        return change_key.strip()
    admin_id = get_admin_id_from_record(record)
    if admin_id:
        return admin_id
    title = str(record.get("title") or "").strip()
    date_value = str(record.get("postDate") or record.get("communityFirstPublishedAt") or "").strip()
    return f"{title}||{date_value}" if title or date_value else repr(record)


def source_label_to_internal(value: str) -> str:
    key = normalize_text_key(value)
    if key == "private":
        return "private"
    if key in {"community", "community release notes", "release notes"}:
        return "community"
    return key


def source_internal_to_label(value: str) -> str:
    key = source_label_to_internal(value)
    if key == "private":
        return SOURCE_PRIVATE
    if key == "community":
        return SOURCE_COMMUNITY
    return value


def get_existing_source_set(fields: Dict[str, Any]) -> Set[str]:
    sources = {
        source_label_to_internal(v)
        for v in normalize_multi_option_values(field_value(fields, CF_SOURCE))
        if source_label_to_internal(v)
    }
    if not sources and normalize_text_key(field_value(fields, CF_ADMIN_ID)):
        sources.add("private")
    return sources


def merge_source_sets(existing_sources: Set[str], record_sources: Set[str]) -> List[str]:
    merged = sorted({source_label_to_internal(s) for s in existing_sources | record_sources if str(s or "").strip()})
    return [source_internal_to_label(s) for s in merged]


def record_has_source(record: Dict[str, Any], source_name: str) -> bool:
    wanted = source_label_to_internal(source_name)
    return wanted in {source_label_to_internal(str(v)) for v in (record.get("_source") or [])}


def extract_date_part(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("start", "end"):
            parsed = extract_date_part(value.get(key))
            if parsed:
                return parsed
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.startswith("{") and raw.endswith("}"):
        try:
            return extract_date_part(json.loads(raw))
        except Exception:
            pass
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    return match.group(1) if match else None


def date_to_field_value(date_value: Any) -> Optional[str]:
    date_text = extract_date_part(date_value)
    if not date_text:
        return None
    if DATE_FIELD_MODE == "jpd":
        return json.dumps({"start": date_text, "end": date_text}, ensure_ascii=False, separators=(",", ":"))
    return date_text


def date_value_same_day(current_value: Any, desired_value: Any) -> bool:
    return extract_date_part(current_value) == extract_date_part(desired_value)


def community_week_range_from_first_published(first_published_value: Any) -> Optional[Dict[str, str]]:
    date_text = extract_date_part(first_published_value)
    if not date_text:
        return None
    try:
        day = datetime.strptime(date_text, "%Y-%m-%d").date()
    except Exception:
        return None
    week_start = day - timedelta(days=day.weekday())
    week_end = week_start + timedelta(days=6)
    return {"start": week_start.isoformat(), "end": week_end.isoformat()}


def community_week_start_field_value(first_published_value: Any) -> Optional[str]:
    week_range = community_week_range_from_first_published(first_published_value)
    return date_to_field_value(week_range["start"]) if week_range else None


def community_week_end_field_value(first_published_value: Any) -> Optional[str]:
    week_range = community_week_range_from_first_published(first_published_value)
    return date_to_field_value(week_range["end"]) if week_range else None


def input_with_default(label: str, default_value: str = "", env_var: Optional[str] = None) -> str:
    env_value = os.getenv(env_var or "", "").strip() if env_var else ""
    effective_default = env_value or default_value or ""
    suffix = f" [{effective_default}]" if effective_default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or effective_default


def secret_with_default(label: str, env_var: Optional[str] = None) -> str:
    env_value = os.getenv(env_var or "", "").strip() if env_var else ""
    if env_value:
        return env_value
    return getpass.getpass(f"{label}: ").strip()


# =============================================================================
# SOURCE HTTP HELPERS
# =============================================================================


def source_request_with_retries(method: str, url: str, **kwargs: Any) -> Optional[requests.Response]:
    timeout = kwargs.pop("timeout", (SOURCE_REQUEST_CONNECT_TIMEOUT_SECONDS, SOURCE_REQUEST_TIMEOUT_SECONDS))
    last_error: Optional[BaseException] = None
    for attempt in range(1, SOURCE_REQUEST_MAX_RETRIES + 1):
        try:
            return requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_error = exc
            print(f"Network error on source request ({attempt}/{SOURCE_REQUEST_MAX_RETRIES}): {exc}")
            if attempt < SOURCE_REQUEST_MAX_RETRIES:
                time.sleep(SOURCE_REQUEST_RETRY_SLEEP_SECONDS * attempt)
    print(f"Source request failed after retries: {last_error}")
    return None


def build_private_urls(org_id: str) -> Dict[str, str]:
    base = (
        "https://admin.atlassian.com/"
        f"gateway/api/admin/private/release-management/v1/organization/{org_id}/product-updates/changes"
    )
    detail_template = (
        "https://admin.atlassian.com/"
        f"gateway/api/admin/private/release-management/v1/organization/{org_id}/product-updates/changes/{{change_id}}"
    )
    return {"list": base, "detail_template": detail_template}


def get_private_headers(org_id: str) -> Optional[Dict[str, str]]:
    print("\n=== PRIVATE ADMIN SOURCE ===")
    print("This optional source uses the customer's own admin.atlassian.com browser session cookie.")
    print("Leave it blank to skip the private source and use only Community Release Notes.")
    cookie_value = secret_with_default("admin.atlassian.com Cookie header", "ATLASSIAN_ADMIN_COOKIE")
    if not cookie_value:
        print("Private source skipped.")
        return None
    return {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Cookie": cookie_value,
        "Referer": f"https://admin.atlassian.com/o/{org_id}/changelog",
        "User-Agent": "Mozilla/5.0",
    }


def fetch_all_private_changes(org_id: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    urls = build_private_urls(org_id)
    params: Dict[str, Any] = {"limit": PRIVATE_PAGE_LIMIT}
    all_changes: List[Dict[str, Any]] = []
    page = 0

    print("\n=== [PRIVATE] Fetching change list ===")
    while True:
        print(f"[PRIVATE] page {page}, limit={PRIVATE_PAGE_LIMIT}")
        resp = source_request_with_retries("GET", urls["list"], headers=headers, params=params)
        if resp is None:
            break
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print(f"Private list request failed: {exc}")
            print(resp.text[:1500])
            break
        payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        links = payload.get("links", {}) if isinstance(payload, dict) else {}
        all_changes.extend(data if isinstance(data, list) else [])
        print(f"  received={len(data) if isinstance(data, list) else 0}, accumulated={len(all_changes)}")
        next_cursor = links.get("next") if isinstance(links, dict) else None
        if not next_cursor:
            break
        params = {"limit": PRIVATE_PAGE_LIMIT, "cursor": next_cursor}
        page += 1

    dedup: Dict[str, Dict[str, Any]] = {}
    for change in all_changes:
        change_id = str(change.get("id") or "").strip()
        if change_id and change_id not in dedup:
            dedup[change_id] = change
    print(f"[PRIVATE] unique changes={len(dedup)}")
    return list(dedup.values())


def fetch_private_change_detail(org_id: str, headers: Dict[str, str], change_id: str) -> Dict[str, Any]:
    url = build_private_urls(org_id)["detail_template"].format(change_id=change_id)
    resp = source_request_with_retries("GET", url, headers=headers)
    if resp is None:
        return {"_detail_error_status": "NETWORK", "_detail_error_message": "Private detail request failed after retries."}
    if resp.status_code == 404:
        return {"_detail_error_status": 404, "_detail_error_message": "Private detail endpoint returned 404."}
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        print(f"Private detail request failed for {change_id}: {exc}")
        print(resp.text[:1500])
        return {"_detail_error_status": resp.status_code, "_detail_error_message": resp.text[:1500]}
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def pick_from_detail_or_base(field: str, base: Dict[str, Any], detail: Dict[str, Any], fallback_field: Optional[str] = None) -> Any:
    if field in detail and detail[field] is not None:
        return detail[field]
    key = fallback_field or field
    return base.get(key)


def normalize_private_change(base_change: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
    pick = lambda field, fallback=None: pick_from_detail_or_base(field, base_change, detail, fallback)
    change_id = pick("id")
    record = {
        "id": change_id,
        "privateId": change_id,
        "adminId": change_id,
        "changeKey": pick("changeKey"),
        "title": pick("title"),
        "products": expand_product_aliases(pick("products") or []),
        "status": normalize_private_status(pick("status")),
        "type": pick("type"),
        "postDate": extract_date_part(pick("postDate")),
        "releaseStartDate": extract_date_part(pick("releaseStartDate")),
        "releaseEndDate": extract_date_part(pick("releaseEndDate")),
        "siteReleaseStatus": str(pick("siteReleaseStatus") or "").strip().upper() or None,
        "summary": pick("summary"),
        "getStarted": pick("getStarted"),
        "keyChanges": pick("keyChanges"),
        "benefitsList": pick("benefitsList"),
        "reasonForChange": pick("reasonForChange"),
        "prepareForChange": pick("prepareForChange"),
        "isDelayable": pick("isDelayable"),
        "isDelayed": pick("isDelayed"),
        "_source": ["private"],
    }
    if detail.get("_detail_error_status"):
        record["observation"] = detail.get("_detail_error_message") or "Private detail endpoint returned an error."
    return record


# =============================================================================
# COMMUNITY RELEASE NOTES SOURCE
# =============================================================================


def fetch_all_community_changes() -> List[Dict[str, Any]]:
    all_changes: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {"limit": COMMUNITY_PAGE_LIMIT}
    page = 0
    seen_ids: Set[str] = set()
    seen_cursors: Set[str] = set()

    print("\n=== [COMMUNITY] Fetching public Release Notes ===")
    while True:
        print(f"[COMMUNITY] page {page}, limit={COMMUNITY_PAGE_LIMIT}")
        resp = source_request_with_retries(
            "GET",
            COMMUNITY_API_URL,
            headers={"Accept": "application/json,text/plain,*/*"},
            params=params,
        )
        if resp is None:
            break
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print(f"Community list request failed: {exc}")
            print(resp.text[:1500])
            break
        payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        links = payload.get("links", {}) if isinstance(payload, dict) else {}
        added = 0
        if isinstance(data, list):
            for change in data:
                change_id = str(change.get("id") or "").strip()
                if change_id and change_id not in seen_ids:
                    seen_ids.add(change_id)
                    all_changes.append(change)
                    added += 1
        print(f"  received={len(data) if isinstance(data, list) else 0}, added={added}, accumulated={len(all_changes)}")
        next_cursor = links.get("next") if isinstance(links, dict) else None
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        params = {"limit": COMMUNITY_PAGE_LIMIT, "cursor": next_cursor}
        page += 1

    print(f"[COMMUNITY] unique changes={len(all_changes)}")
    return all_changes


def parse_community_detail_payload(resp: requests.Response) -> Dict[str, Any]:
    payload = resp.json()
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def fetch_community_change_detail(change_id: str) -> Dict[str, Any]:
    if not change_id:
        return {}
    url = COMMUNITY_DETAIL_URL_TEMPLATE.format(change_id=change_id)
    resp = source_request_with_retries("GET", url, headers={"Accept": "application/json"})
    if resp and resp.status_code in (200, 201):
        try:
            return parse_community_detail_payload(resp)
        except Exception as exc:
            print(f"Community detail parse failed for {change_id}: {exc}")
            return {}

    status = resp.status_code if resp else "NETWORK"
    print(f"Community detail request failed for {change_id}: HTTP {status}. Trying legacy endpoint once.")
    legacy_url = COMMUNITY_LEGACY_DETAIL_URL_TEMPLATE.format(change_id=change_id)
    legacy_resp = source_request_with_retries("GET", legacy_url, headers={"Accept": "application/json"})
    if legacy_resp and legacy_resp.status_code in (200, 201):
        try:
            return parse_community_detail_payload(legacy_resp)
        except Exception:
            return {}
    return {}


def normalize_community_change(base_change: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
    pick = lambda field, fallback=None: pick_from_detail_or_base(field, base_change, detail, fallback)
    change_id = pick("id")
    community_products = pick("products") or []
    return {
        "id": change_id,
        "communityId": change_id,
        "adminId": change_id,
        "title": pick("title"),
        "products": get_community_technical_products(community_products),
        "communityRawProducts": merge_unique(community_products),
        "communityStatus": normalize_private_status(pick("status")),
        "communityType": pick("type"),
        "communityReleaseStartDate": extract_date_part(pick("releaseStartDate")),
        "communityReleaseEndDate": extract_date_part(pick("releaseEndDate")),
        "communityFirstPublishedAt": extract_date_part(pick("firstPublishedAt")),
        "communityCategory": pick("category"),
        "summary": pick("summary"),
        "getStarted": pick("getStarted"),
        "keyChanges": pick("keyChanges"),
        "benefitsList": pick("benefitsList"),
        "reasonForChange": pick("reasonForChange"),
        "prepareForChange": pick("prepareForChange"),
        "informedAboutChange": pick("informedAboutChange"),
        "affectedByChange": pick("affectedByChange"),
        "relatedLinks": pick("relatedLinks"),
        "featuredImage": pick("featuredImage"),
        "status": None,
        "type": None,
        "postDate": None,
        "releaseStartDate": None,
        "releaseEndDate": None,
        "siteReleaseStatus": None,
        "changeKey": None,
        "_source": ["community"],
    }


def collect_community_source() -> List[Dict[str, Any]]:
    return [normalize_community_change(change, {}) for change in fetch_all_community_changes()]


# =============================================================================
# MERGE AND INDEXING
# =============================================================================


def merge_records(current: Dict[str, Any], incoming: Dict[str, Any], source_label: str) -> Dict[str, Any]:
    current["products"] = expand_product_aliases(merge_unique(current.get("products"), incoming.get("products")))
    incoming_admin_id = get_admin_id_from_record(incoming)
    if incoming_admin_id:
        current.setdefault("adminId", incoming_admin_id)
        if source_label_to_internal(source_label) == "community":
            current.setdefault("communityId", incoming_admin_id)
        if source_label_to_internal(source_label) == "private":
            current.setdefault("privateId", incoming_admin_id)

    for key, value in incoming.items():
        if key in {"products", "_source"}:
            continue
        if key == "id":
            if not current.get("id"):
                current[key] = value
            continue
        if key not in current or current[key] in (None, "", [], {}):
            current[key] = value

    sources = {source_label_to_internal(str(s)) for s in current.get("_source", [])}
    sources.add(source_label_to_internal(source_label))
    current["_source"] = sorted(sources)
    return current


def merge_private_and_community(private_records: List[Dict[str, Any]], community_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    title_index: Dict[str, str] = {}

    def put_record(record: Dict[str, Any], source_label: str) -> None:
        item = dict(record)
        item["products"] = expand_product_aliases(item.get("products"))
        item["_source"] = sorted({source_label_to_internal(str(s)) for s in (item.get("_source") or [source_label])})
        key = get_change_key(item)
        title_key = normalize_text_key(item.get("title"))
        target_key = key
        admin_id = normalize_text_key(get_admin_id_from_record(item))
        if admin_id and admin_id in merged:
            target_key = admin_id
        elif target_key not in merged and title_key and title_key in title_index:
            target_key = title_index[title_key]
        if target_key in merged:
            merged[target_key] = merge_records(merged[target_key], item, source_label)
        else:
            merged[target_key] = item
        if admin_id:
            merged.setdefault(admin_id, merged[target_key])
        if title_key:
            title_index.setdefault(title_key, target_key)

    for record in private_records:
        put_record(record, "private")
    for record in community_records:
        put_record(record, "community")

    # Remove duplicated object aliases created by admin-id indexing.
    unique: Dict[int, Dict[str, Any]] = {}
    for value in merged.values():
        unique[id(value)] = value
    return list(unique.values())


def build_private_indexes(private_records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    indexes = {"by_admin_id": {}, "by_change_key": {}, "by_title": {}}
    for record in private_records:
        admin_id = normalize_text_key(get_admin_id_from_record(record))
        change_key = normalize_text_key(record.get("changeKey"))
        title = normalize_text_key(record.get("title"))
        if admin_id:
            indexes["by_admin_id"][admin_id] = record
        if change_key:
            indexes["by_change_key"][change_key] = record
        if title:
            indexes["by_title"][title] = record
    return indexes


def build_community_indexes(community_records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    indexes = {"by_admin_id": {}, "by_title": {}}
    for record in community_records:
        admin_id = normalize_text_key(get_admin_id_from_record(record))
        title = normalize_text_key(record.get("title"))
        if admin_id:
            indexes["by_admin_id"][admin_id] = record
        if title:
            indexes["by_title"][title] = record
    return indexes


def find_related_community_record(record: Dict[str, Any], community_indexes: Dict[str, Dict[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    admin_id = normalize_text_key(get_admin_id_from_record(record))
    if admin_id and admin_id in community_indexes["by_admin_id"]:
        return community_indexes["by_admin_id"][admin_id]
    title = normalize_text_key(record.get("title"))
    if title and title in community_indexes["by_title"]:
        return community_indexes["by_title"][title]
    return None


def find_related_private_record(record: Dict[str, Any], private_indexes: Dict[str, Dict[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    admin_id = normalize_text_key(get_admin_id_from_record(record))
    if admin_id and admin_id in private_indexes["by_admin_id"]:
        return private_indexes["by_admin_id"][admin_id]
    change_key = normalize_text_key(record.get("changeKey"))
    if change_key and change_key in private_indexes["by_change_key"]:
        return private_indexes["by_change_key"][change_key]
    title = normalize_text_key(record.get("title"))
    if title and title in private_indexes["by_title"]:
        return private_indexes["by_title"][title]
    return None


def enrich_record(
    candidate: Dict[str, Any],
    private_base_by_id: Dict[str, Dict[str, Any]],
    private_indexes: Dict[str, Dict[str, Dict[str, Any]]],
    community_indexes: Dict[str, Dict[str, Dict[str, Any]]],
    org_id: str,
    private_headers: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    sources = {source_label_to_internal(str(s)) for s in candidate.get("_source") or []}
    related_community = find_related_community_record(candidate, community_indexes)
    related_private = find_related_private_record(candidate, private_indexes)
    full: Optional[Dict[str, Any]] = None

    if "private" in sources and related_private:
        private_id = get_admin_id_from_record(related_private)
        if private_id and private_id in private_base_by_id and private_headers:
            detail = fetch_private_change_detail(org_id, private_headers, private_id)
            full = normalize_private_change(private_base_by_id[private_id], detail)
        else:
            full = dict(related_private)
        full["_source"] = ["private"]

    if "community" in sources and related_community:
        community_id = get_admin_id_from_record(related_community)
        detail = fetch_community_change_detail(community_id or "") if community_id else {}
        community_full = normalize_community_change(related_community, detail)
        community_full["_source"] = ["community"]
        full = merge_records(full, community_full, "community") if full else community_full

    if full is None:
        full = dict(candidate)

    if related_private and "private" not in {source_label_to_internal(str(s)) for s in full.get("_source", [])}:
        full = merge_records(full, related_private, "private")
    if related_community and "community" not in {source_label_to_internal(str(s)) for s in full.get("_source", [])}:
        full = merge_records(full, related_community, "community")
    return full


# =============================================================================
# ADF DESCRIPTION
# =============================================================================


def parse_adf_content(adf_value: Any) -> List[Dict[str, Any]]:
    if not adf_value:
        return []
    if isinstance(adf_value, dict):
        doc = adf_value
    else:
        try:
            doc = json.loads(adf_value)
        except Exception:
            return []
    content = doc.get("content") if isinstance(doc, dict) else None
    return content if isinstance(content, list) else []


def add_text_paragraph(content: List[Dict[str, Any]], text: str, strong: bool = False) -> None:
    node: Dict[str, Any] = {"type": "text", "text": text}
    if strong:
        node["marks"] = [{"type": "strong"}]
    content.append({"type": "paragraph", "content": [node]})


def build_issue_description_adf(record: Dict[str, Any]) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []

    def add_section(label: str, value: Any) -> None:
        blocks = parse_adf_content(value)
        if not blocks:
            return
        add_text_paragraph(content, label, strong=True)
        content.extend(blocks)
        content.append({"type": "paragraph", "content": []})

    add_section("Summary", record.get("summary"))
    add_section("Key changes", record.get("keyChanges"))
    add_section("Benefits", record.get("benefitsList"))
    add_section("How to get started", record.get("getStarted"))
    add_section("Reason for change", record.get("reasonForChange"))
    add_section("Prepare for change", record.get("prepareForChange"))
    add_section("Informed about change", record.get("informedAboutChange"))
    add_section("Affected by change", record.get("affectedByChange"))

    if not content:
        add_text_paragraph(content, "No detailed content available for this change.")

    sources = [source_internal_to_label(str(s)) for s in record.get("_source", [])]
    if sources:
        add_text_paragraph(content, f"Sources: {', '.join(sources)}")

    admin_id = get_admin_id_from_record(record)
    if admin_id:
        add_text_paragraph(content, f"Atlassian change id: {admin_id}")

    observation = record.get("observation")
    if observation:
        add_text_paragraph(content, f"Note: {observation}")

    return {"type": "doc", "version": 1, "content": content}


# =============================================================================
# JIRA API
# =============================================================================


def jira_request(method: str, url: str, email: str, api_token: str, **kwargs: Any) -> requests.Response:
    return requests.request(
        method,
        url,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        auth=(email, api_token),
        timeout=90,
        **kwargs,
    )


def fetch_project_issue_types(base_url: str, project_key: str, email: str, api_token: str) -> List[Dict[str, Any]]:
    url = base_url.rstrip("/") + f"/rest/api/3/project/{project_key}"
    resp = jira_request("GET", url, email, api_token, params={"expand": "issueTypes"})
    if resp.status_code >= 400:
        print(f"Could not load issue types: HTTP {resp.status_code} {resp.text[:500]}")
        return []
    payload = resp.json()
    return payload.get("issueTypes", []) if isinstance(payload, dict) else []


def resolve_issue_type_id_for_project(base_url: str, project_key: str, email: str, api_token: str, configured_issue_type: str) -> str:
    configured_value = str(configured_issue_type or "").strip()
    if not configured_value:
        raise ValueError("Issue type is required. Provide either issue type name or issue type id.")
    issue_types = fetch_project_issue_types(base_url, project_key, email, api_token)
    if not issue_types:
        return configured_value
    by_id = {str(item.get("id")): item for item in issue_types if item.get("id")}
    by_name = {str(item.get("name", "")).strip().lower(): item for item in issue_types if item.get("name")}
    if configured_value in by_id:
        selected = by_id[configured_value]
        print(f"Issue type validated: {selected.get('name')} ({selected.get('id')})")
        return str(selected["id"])
    if configured_value.lower() in by_name:
        selected = by_name[configured_value.lower()]
        print(f"Issue type resolved: {selected.get('name')} ({selected.get('id')})")
        return str(selected["id"])
    print("Valid issue types found:")
    for item in issue_types:
        print(f"  - {item.get('name')} | id={item.get('id')}")
    raise ValueError(f"Issue type is not valid for project {project_key}: {configured_value}")


def search_existing_issues(base_url: str, project_key: str, email: str, api_token: str) -> List[Dict[str, Any]]:
    fields = [
        "summary",
        "description",
        CF_CHANGEKEY,
        CF_ADMIN_ID,
        CF_SOURCE,
        CF_PRODUCTS,
        CF_CHANGE_TYPE,
        CF_CHANGE_STATUS,
        CF_SITE_STATUS,
        CF_POSTDATE,
        CF_RELEASE_START,
        CF_RELEASE_END,
        CF_IS_DELAYABLE,
        CF_IS_DELAYED,
        CF_COMMUNITY_STATUS,
        CF_COMMUNITY_CHANGE_TYPE,
        CF_COMMUNITY_RELEASE_START,
        CF_COMMUNITY_FIRST_PUBLISHED,
        CF_COMMUNITY_WEEK_START,
        CF_COMMUNITY_WEEK_END,
    ]
    fields = [field for field in fields if field]
    all_issues: List[Dict[str, Any]] = []
    next_page_token: Optional[str] = None
    print("\n=== [JIRA] Loading existing issues ===")
    while True:
        body: Dict[str, Any] = {
            "jql": f"project = {project_key} ORDER BY created DESC",
            "maxResults": 100,
            "fields": fields,
            "fieldsByKeys": False,
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token
        url = base_url.rstrip("/") + "/rest/api/3/search/jql"
        resp = jira_request("POST", url, email, api_token, data=json.dumps(body))
        resp.raise_for_status()
        payload = resp.json()
        issues = payload.get("issues", []) if isinstance(payload, dict) else []
        all_issues.extend(issues)
        next_page_token = payload.get("nextPageToken") if isinstance(payload, dict) else None
        is_last = payload.get("isLast", True) if isinstance(payload, dict) else True
        print(f"  loaded={len(issues)}, accumulated={len(all_issues)}, isLast={is_last}")
        if is_last or not next_page_token or not issues:
            break
    return all_issues


def build_existing_issue_indexes(issues: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    indexes = {"by_admin_id": {}, "by_change_key": {}, "by_title": {}}
    for issue in issues:
        fields = issue.get("fields", {})
        admin_id = normalize_text_key(field_value(fields, CF_ADMIN_ID))
        change_key = normalize_text_key(field_value(fields, CF_CHANGEKEY))
        summary = fields.get("summary") or ""
        title = normalize_text_key(re.sub(r"^\[[^\]]+\]\s*", "", str(summary)).strip())
        if admin_id:
            indexes["by_admin_id"][admin_id] = issue
        if change_key:
            indexes["by_change_key"][change_key] = issue
        if title:
            indexes["by_title"][title] = issue
    return indexes


def find_matching_issue(record: Dict[str, Any], indexes: Dict[str, Dict[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    admin_id = normalize_text_key(get_admin_id_from_record(record))
    if admin_id and admin_id in indexes["by_admin_id"]:
        return indexes["by_admin_id"][admin_id]
    change_key = normalize_text_key(record.get("changeKey"))
    if change_key and change_key in indexes["by_change_key"]:
        return indexes["by_change_key"][change_key]
    title = normalize_text_key(record.get("title"))
    if title and title in indexes["by_title"]:
        return indexes["by_title"][title]
    return None


def jira_admin_request(base_url: str, email: str, api_token: str, method: str, path: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    url = base_url.rstrip("/") + path
    try:
        resp = jira_request(method, url, email, api_token, **kwargs)
        if resp.status_code >= 400:
            print(f"Jira admin request failed: {method} {path} -> HTTP {resp.status_code} {resp.text[:500]}")
            return None
        return resp.json() if resp.text.strip() else {}
    except Exception as exc:
        print(f"Jira admin request failed: {method} {path} -> {exc}")
        return None


def get_field_context_id(base_url: str, email: str, api_token: str, field_id: str) -> Optional[str]:
    if not configured(field_id):
        return None
    if field_id in FIELD_CONTEXT_IDS and FIELD_CONTEXT_IDS[field_id]:
        return FIELD_CONTEXT_IDS[field_id]
    payload = jira_admin_request(base_url, email, api_token, "GET", f"/rest/api/3/field/{field_id}/context")
    values = payload.get("values", []) if isinstance(payload, dict) else []
    if len(values) == 1:
        context_id = str(values[0].get("id"))
        FIELD_CONTEXT_IDS[field_id] = context_id
        return context_id
    if len(values) > 1:
        print(f"Field {field_id} has multiple contexts. Set FIELD_CONTEXT_IDS['{field_id}'] manually if option creation is needed.")
    return None


def get_existing_field_options(base_url: str, email: str, api_token: str, field_id: str, context_id: str) -> Set[str]:
    existing: Set[str] = set()
    start_at = 0
    while True:
        payload = jira_admin_request(
            base_url,
            email,
            api_token,
            "GET",
            f"/rest/api/3/field/{field_id}/context/{context_id}/option",
            params={"startAt": start_at, "maxResults": 100},
        )
        if not payload:
            break
        values = payload.get("values", [])
        for item in values:
            existing.add(normalize_value_for_compare(item.get("value")))
        if payload.get("isLast", True):
            break
        start_at += len(values)
    return existing


def ensure_field_options(base_url: str, email: str, api_token: str, field_id: str, values: Iterable[str], dry_run: bool) -> None:
    if not AUTO_CREATE_FIELD_OPTIONS or not configured(field_id):
        return
    desired = sorted({str(value).strip() for value in values if str(value or "").strip()})
    if not desired:
        return
    context_id = get_field_context_id(base_url, email, api_token, field_id)
    if not context_id:
        return
    existing = get_existing_field_options(base_url, email, api_token, field_id, context_id)
    missing = [value for value in desired if normalize_value_for_compare(value) not in existing]
    if not missing:
        return
    print(f"[JIRA OPTIONS] Field {field_id}: missing options {missing}")
    if dry_run:
        return
    payload = {"options": [{"value": value} for value in missing]}
    jira_admin_request(
        base_url,
        email,
        api_token,
        "POST",
        f"/rest/api/3/field/{field_id}/context/{context_id}/option",
        data=json.dumps(payload),
    )



def ensure_options_for_records(base_url: str, email: str, api_token: str, records: List[Dict[str, Any]], dry_run: bool) -> None:
    if not AUTO_CREATE_FIELD_OPTIONS:
        return
    print("\n=== [JIRA OPTIONS] Checking missing select options ===")
    source_values = []
    product_values = []
    private_status_values = [NEW_THIS_WEEK_VALUE]
    change_type_values = []
    site_status_values = []
    community_status_values = [NEW_THIS_WEEK_VALUE]
    community_type_values = []
    yes_no_values = ["Yes", "No"]

    for record in records:
        for source in record.get("_source") or []:
            source_values.append(source_internal_to_label(str(source)))
        product_values.extend(record.get("products") or [])
        if record.get("status"):
            private_status_values.append(str(record["status"]))
        if record.get("type"):
            change_type_values.append(str(record["type"]))
        if record.get("siteReleaseStatus"):
            site_status_values.append(str(record["siteReleaseStatus"]))
        if record.get("communityStatus"):
            community_status_values.append(str(record["communityStatus"]))
        if record.get("communityType"):
            community_type_values.append(str(record["communityType"]))

    ensure_field_options(base_url, email, api_token, CF_SOURCE, source_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_PRODUCTS, product_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_CHANGE_STATUS, private_status_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_CHANGE_TYPE, change_type_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_SITE_STATUS, site_status_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_COMMUNITY_STATUS, community_status_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_COMMUNITY_CHANGE_TYPE, community_type_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_IS_DELAYABLE, yes_no_values, dry_run)
    ensure_field_options(base_url, email, api_token, CF_IS_DELAYED, yes_no_values, dry_run)


# =============================================================================
# JIRA CREATE / UPDATE PAYLOADS
# =============================================================================


def put_field(fields: Dict[str, Any], field_id: str, value: Any) -> None:
    if configured(field_id) and value is not None:
        fields[field_id] = value


def yes_no_multi(value: Any) -> List[Dict[str, str]]:
    if value is True:
        return [{"value": "Yes"}]
    if value is False:
        return [{"value": "No"}]
    return []


def build_create_fields(project_key: str, issue_type_id: str, record: Dict[str, Any], force_new_this_week: bool) -> Dict[str, Any]:
    admin_id = get_admin_id_from_record(record)
    change_key = record.get("changeKey")
    title = record.get("title") or "Unnamed Atlassian change"
    summary_token = change_key or admin_id
    summary = f"[{summary_token}] {title}" if summary_token else title

    fields: Dict[str, Any] = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"id": str(issue_type_id)},
        "description": build_issue_description_adf(record),
    }

    put_field(fields, CF_CHANGEKEY, change_key)
    put_field(fields, CF_ADMIN_ID, admin_id)
    put_field(fields, CF_PRODUCTS, to_multi_options(record.get("products") or []))
    put_field(fields, CF_SOURCE, to_multi_options(source_internal_to_label(str(s)) for s in (record.get("_source") or [])))
    put_field(fields, CF_CHANGE_TYPE, to_option(record.get("type")) if record.get("type") else None)
    put_field(fields, CF_SITE_STATUS, to_option(record.get("siteReleaseStatus")) if record.get("siteReleaseStatus") else None)
    put_field(fields, CF_POSTDATE, date_to_field_value(record.get("postDate")))
    put_field(fields, CF_RELEASE_START, date_to_field_value(record.get("releaseStartDate")))
    put_field(fields, CF_RELEASE_END, date_to_field_value(record.get("releaseEndDate")))
    put_field(fields, CF_IS_DELAYABLE, yes_no_multi(record.get("isDelayable")))
    put_field(fields, CF_IS_DELAYED, yes_no_multi(record.get("isDelayed")))

    if force_new_this_week:
        if record_has_source(record, "private"):
            put_field(fields, CF_CHANGE_STATUS, to_option(NEW_THIS_WEEK_VALUE))
    else:
        put_field(fields, CF_CHANGE_STATUS, to_option(record.get("status")) if record.get("status") else None)

    if record.get("communityStatus"):
        community_status = NEW_THIS_WEEK_VALUE if force_new_this_week else str(record["communityStatus"])
        put_field(fields, CF_COMMUNITY_STATUS, to_option(community_status))
    if record.get("communityType"):
        put_field(fields, CF_COMMUNITY_CHANGE_TYPE, to_multi_options([str(record["communityType"])]))
    put_field(fields, CF_COMMUNITY_RELEASE_START, date_to_field_value(record.get("communityReleaseStartDate")))
    put_field(fields, CF_COMMUNITY_FIRST_PUBLISHED, date_to_field_value(record.get("communityFirstPublishedAt")))
    put_field(fields, CF_COMMUNITY_WEEK_START, community_week_start_field_value(record.get("communityFirstPublishedAt")))
    put_field(fields, CF_COMMUNITY_WEEK_END, community_week_end_field_value(record.get("communityFirstPublishedAt")))
    return fields


def create_jira_issue(base_url: str, project_key: str, issue_type_id: str, email: str, api_token: str, record: Dict[str, Any], force_new_this_week: bool, dry_run: bool) -> Tuple[Optional[str], Dict[str, Any]]:
    fields = build_create_fields(project_key, issue_type_id, record, force_new_this_week)
    payload = {"fields": fields}
    print(f"Creating Jira issue for: {record.get('title')}")
    if dry_run:
        print("  dry-run: issue not created")
        return None, payload
    url = base_url.rstrip("/") + "/rest/api/3/issue"
    resp = jira_request("POST", url, email, api_token, data=json.dumps(payload))
    if resp.status_code not in (200, 201):
        print(f"Create failed: HTTP {resp.status_code}")
        try:
            error_payload = resp.json()
        except Exception:
            error_payload = {"rawText": resp.text}
        print(error_payload)
        payload["_jira_create_failed"] = True
        payload["_jira_create_status_code"] = resp.status_code
        payload["_jira_create_error"] = error_payload
        return None, payload
    issue_key = resp.json().get("key")
    print(f"Created: {issue_key}")
    return issue_key, payload


def derive_actual_change_status(record: Dict[str, Any]) -> Optional[str]:
    if not record_has_source(record, "private"):
        return None
    status = normalize_private_status(record.get("status"))
    if not status or normalize_value_for_compare(status) == normalize_value_for_compare(NEW_THIS_WEEK_VALUE):
        return None
    return status


def build_update_fields(existing_issue: Dict[str, Any], full_record: Dict[str, Any]) -> Dict[str, Any]:
    fields = existing_issue.get("fields", {})
    current_sources = get_existing_source_set(fields)
    record_sources = {source_label_to_internal(str(s)) for s in (full_record.get("_source") or []) if str(s).strip()}
    first_private_appearance = "private" in record_sources and "private" not in current_sources
    first_community_appearance = "community" in record_sources and "community" not in current_sources
    source_added = bool(record_sources - current_sources)

    current_products = expand_product_aliases(normalize_multi_option_values(field_value(fields, CF_PRODUCTS)))
    current_change_status = normalize_single_option_value(field_value(fields, CF_CHANGE_STATUS))
    current_change_type = normalize_single_option_value(field_value(fields, CF_CHANGE_TYPE))
    current_site_status = normalize_single_option_value(field_value(fields, CF_SITE_STATUS))
    current_community_status = normalize_single_option_value(field_value(fields, CF_COMMUNITY_STATUS))
    current_community_type = normalize_multi_option_values(field_value(fields, CF_COMMUNITY_CHANGE_TYPE))

    update_fields: Dict[str, Any] = {}

    desired_source_labels = merge_source_sets(current_sources, record_sources)
    if desired_source_labels and sort_normalized_list(normalize_multi_option_values(field_value(fields, CF_SOURCE))) != sort_normalized_list(desired_source_labels):
        put_field(update_fields, CF_SOURCE, to_multi_options(desired_source_labels))

    desired_products = expand_product_aliases(merge_unique(current_products, full_record.get("products") or []))
    if desired_products and sort_normalized_list(current_products) != sort_normalized_list(desired_products):
        put_field(update_fields, CF_PRODUCTS, to_multi_options(desired_products))

    desired_admin_id = get_admin_id_from_record(full_record)
    current_admin_id = normalize_text_key(field_value(fields, CF_ADMIN_ID))
    if desired_admin_id and normalize_text_key(desired_admin_id) != current_admin_id:
        put_field(update_fields, CF_ADMIN_ID, str(desired_admin_id))

    desired_change_type = full_record.get("type")
    if desired_change_type and normalize_value_for_compare(desired_change_type) != normalize_value_for_compare(current_change_type):
        put_field(update_fields, CF_CHANGE_TYPE, to_option(str(desired_change_type)))

    desired_site_status = full_record.get("siteReleaseStatus")
    if desired_site_status and normalize_value_for_compare(desired_site_status) != normalize_value_for_compare(current_site_status):
        put_field(update_fields, CF_SITE_STATUS, to_option(str(desired_site_status)))

    for field_id, desired_date in [
        (CF_POSTDATE, full_record.get("postDate")),
        (CF_RELEASE_START, full_record.get("releaseStartDate")),
        (CF_RELEASE_END, full_record.get("releaseEndDate")),
        (CF_COMMUNITY_RELEASE_START, full_record.get("communityReleaseStartDate")),
        (CF_COMMUNITY_FIRST_PUBLISHED, full_record.get("communityFirstPublishedAt")),
    ]:
        desired_value = date_to_field_value(desired_date)
        if configured(field_id) and desired_value and not date_value_same_day(field_value(fields, field_id), desired_value):
            put_field(update_fields, field_id, desired_value)

    if full_record.get("communityFirstPublishedAt"):
        week_start_value = community_week_start_field_value(full_record.get("communityFirstPublishedAt"))
        week_end_value = community_week_end_field_value(full_record.get("communityFirstPublishedAt"))
        if configured(CF_COMMUNITY_WEEK_START) and week_start_value and not date_value_same_day(field_value(fields, CF_COMMUNITY_WEEK_START), week_start_value):
            put_field(update_fields, CF_COMMUNITY_WEEK_START, week_start_value)
        if configured(CF_COMMUNITY_WEEK_END) and week_end_value and not date_value_same_day(field_value(fields, CF_COMMUNITY_WEEK_END), week_end_value):
            put_field(update_fields, CF_COMMUNITY_WEEK_END, week_end_value)

    if full_record.get("isDelayable") is not None:
        put_field(update_fields, CF_IS_DELAYABLE, yes_no_multi(full_record.get("isDelayable")))
    if full_record.get("isDelayed") is not None:
        put_field(update_fields, CF_IS_DELAYED, yes_no_multi(full_record.get("isDelayed")))

    desired_community_status = full_record.get("communityStatus")
    if desired_community_status:
        actual_value = str(desired_community_status)
        if first_community_appearance:
            desired_value = NEW_THIS_WEEK_VALUE
        elif normalize_value_for_compare(current_community_status) == normalize_value_for_compare(NEW_THIS_WEEK_VALUE):
            desired_value = actual_value
        else:
            desired_value = actual_value
        if normalize_value_for_compare(current_community_status) != normalize_value_for_compare(desired_value):
            put_field(update_fields, CF_COMMUNITY_STATUS, to_option(desired_value))

    desired_community_type = full_record.get("communityType")
    if desired_community_type:
        desired_values = [str(desired_community_type)]
        if sort_normalized_list(current_community_type) != sort_normalized_list(desired_values):
            put_field(update_fields, CF_COMMUNITY_CHANGE_TYPE, to_multi_options(desired_values))

    if source_added and UPDATE_DESCRIPTION_ON_SOURCE_ADDED:
        update_fields["description"] = build_issue_description_adf(full_record)

    actual_change_status = derive_actual_change_status(full_record)
    if first_private_appearance:
        put_field(update_fields, CF_CHANGE_STATUS, to_option(NEW_THIS_WEEK_VALUE))
    elif actual_change_status:
        current_cmp = normalize_value_for_compare(current_change_status)
        actual_cmp = normalize_value_for_compare(actual_change_status)
        if current_cmp == normalize_value_for_compare(NEW_THIS_WEEK_VALUE) or current_cmp != actual_cmp:
            put_field(update_fields, CF_CHANGE_STATUS, to_option(actual_change_status))


    return update_fields


def parse_jira_error_response(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"rawText": resp.text}


def should_retry_update_without_description(error_payload: Dict[str, Any], fields: Dict[str, Any]) -> bool:
    if "description" not in fields:
        return False
    errors = error_payload.get("errors")
    if isinstance(errors, dict) and errors:
        return False
    messages = " ".join(str(item) for item in error_payload.get("errorMessages", []))
    return not messages or messages.strip().upper() == "N/A" or "DESCRIPTION" in messages.upper() or "ADF" in messages.upper()


def write_jira_update_failure_log(issue_key: str, payload: Dict[str, Any], error_payload: Dict[str, Any], suffix: str) -> Path:
    failed_dir = Path("jira_failed_payloads")
    failed_dir.mkdir(exist_ok=True)
    safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", issue_key)[:120]
    path = failed_dir / f"{safe_key}_{suffix}.json"
    path.write_text(json.dumps({"issueKey": issue_key, "error": error_payload, "payload": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def update_jira_issue_fields(base_url: str, issue_key: str, email: str, api_token: str, fields: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    payload = {"fields": fields}
    print(f"Updating {issue_key}")
    if dry_run:
        print("  dry-run: issue not updated")
        return payload
    url = base_url.rstrip("/") + f"/rest/api/3/issue/{issue_key}"
    resp = jira_request("PUT", url, email, api_token, data=json.dumps(payload))
    if resp.status_code in (200, 204):
        print(f"Updated: {issue_key}")
        return payload
    error_payload = parse_jira_error_response(resp)
    print(f"Update failed for {issue_key}: HTTP {resp.status_code}")
    print(error_payload)
    failure_path = write_jira_update_failure_log(issue_key, payload, error_payload, "original")
    print(f"Original payload saved at: {failure_path.resolve()}")
    if should_retry_update_without_description(error_payload, fields):
        retry_fields = dict(fields)
        retry_fields.pop("description", None)
        if retry_fields:
            retry_payload = {"fields": retry_fields}
            print("Retrying without description...")
            retry_resp = jira_request("PUT", url, email, api_token, data=json.dumps(retry_payload))
            if retry_resp.status_code in (200, 204):
                retry_payload["_originalPayloadFailed"] = payload
                retry_payload["_retryReason"] = "Original update failed with a generic description/ADF error."
                return retry_payload
            retry_error = parse_jira_error_response(retry_resp)
            retry_path = write_jira_update_failure_log(issue_key, retry_payload, retry_error, "retry_without_description")
            print(f"Retry payload saved at: {retry_path.resolve()}")
    payload["_jira_update_failed"] = True
    payload["_jira_update_status_code"] = resp.status_code
    payload["_jira_update_error"] = error_payload
    return payload


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    print("=== Atlassian Release Updater: Private Admin + Community Release Notes ===")
    print(f"Date field mode: {DATE_FIELD_MODE}")
    print("Leave optional values blank when you do not want to use that source or feature.")

    org_id = input_with_default("Atlassian ORG_ID", DEFAULT_ORG_ID, "ATLASSIAN_ORG_ID")
    private_headers = get_private_headers(org_id) if org_id else None

    print("\n=== JIRA CONNECTION ===")
    jira_base_url = input_with_default("JIRA_BASE_URL", DEFAULT_JIRA_BASE_URL, "JIRA_BASE_URL")
    project_key = input_with_default("JIRA_PROJECT_KEY", DEFAULT_JIRA_PROJECT_KEY, "JIRA_PROJECT_KEY")
    issue_type = input_with_default("JIRA_ISSUE_TYPE name or id", DEFAULT_JIRA_ISSUE_TYPE, "JIRA_ISSUE_TYPE")
    jira_email = input_with_default("JIRA_EMAIL", DEFAULT_JIRA_EMAIL, "JIRA_EMAIL")
    jira_api_token = secret_with_default("JIRA_API_TOKEN", "JIRA_API_TOKEN")

    if not all([jira_base_url, project_key, issue_type, jira_email, jira_api_token]):
        raise ValueError("Jira connection parameters are incomplete.")

    issue_type_id = resolve_issue_type_id_for_project(jira_base_url, project_key, jira_email, jira_api_token, issue_type)

    dry_run_answer = input("\nRun in DRY-RUN mode, without creating/updating issues? (y/N): ").strip().lower()
    dry_run = dry_run_answer in {"y", "yes"}

    create_missing_answer = input(
        f"Create Jira issues that do not exist yet? ({'Y/n' if CREATE_MISSING_ISSUES_DEFAULT else 'y/N'}): "
    ).strip().lower()
    if not create_missing_answer:
        create_missing_issues = CREATE_MISSING_ISSUES_DEFAULT
    else:
        create_missing_issues = create_missing_answer in {"y", "yes"}

    actions_output = input_with_default("Actions JSON output file", DEFAULT_ACTIONS_OUTPUT, "ACTIONS_OUTPUT")

    private_base_changes: List[Dict[str, Any]] = []
    private_light_records: List[Dict[str, Any]] = []
    private_base_by_id: Dict[str, Dict[str, Any]] = {}

    if private_headers:
        private_base_changes = fetch_all_private_changes(org_id, private_headers)
        private_base_by_id = {str(ch.get("id")): ch for ch in private_base_changes if ch.get("id") is not None}
        private_light_records = [normalize_private_change(ch, {}) for ch in private_base_changes]
    else:
        print("\n[PRIVATE] skipped")

    community_records = collect_community_source()
    private_indexes = build_private_indexes(private_light_records)
    community_indexes = build_community_indexes(community_records)
    merged_weekly = merge_private_and_community(private_light_records, community_records)
    print(f"\n[MERGE] records to compare: {len(merged_weekly)}")

    ensure_options_for_records(jira_base_url, jira_email, jira_api_token, merged_weekly, dry_run)
    existing_issues = search_existing_issues(jira_base_url, project_key, jira_email, jira_api_token)
    existing_indexes = build_existing_issue_indexes(existing_issues)

    actions: Dict[str, Any] = {
        "created": [],
        "create_failed": [],
        "updated": [],
        "skipped": [],
        "metadata": {
            "dry_run": dry_run,
            "date_field_mode": DATE_FIELD_MODE,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "weekly_records": len(merged_weekly),
            "private_records": len(private_light_records),
            "community_records": len(community_records),
            "existing_issues": len(existing_issues),
            "sources": [SOURCE_PRIVATE if private_headers else None, SOURCE_COMMUNITY],
        },
    }

    processed_issue_keys: Set[str] = set()
    for index, record in enumerate(merged_weekly, start=1):
        print(f"\n[{index}/{len(merged_weekly)}] {record.get('title')}")
        full_record = enrich_record(record, private_base_by_id, private_indexes, community_indexes, org_id, private_headers)
        issue = find_matching_issue(full_record, existing_indexes) or find_matching_issue(record, existing_indexes)

        if issue and issue.get("key"):
            processed_issue_keys.add(str(issue["key"]))

        if not issue:
            if not create_missing_issues:
                actions["skipped"].append({
                    "issueKey": None,
                    "adminId": get_admin_id_from_record(full_record),
                    "title": full_record.get("title"),
                    "source": full_record.get("_source"),
                    "reason": "No matching issue and create_missing_issues=False",
                })
                continue
            issue_key, payload = create_jira_issue(
                jira_base_url,
                project_key,
                issue_type_id,
                jira_email,
                jira_api_token,
                full_record,
                force_new_this_week=True,
                dry_run=dry_run,
            )
            action = {
                "issueKey": issue_key,
                "adminId": get_admin_id_from_record(full_record),
                "changeKey": full_record.get("changeKey"),
                "title": full_record.get("title"),
                "source": full_record.get("_source"),
                "payload": payload,
            }
            if issue_key or dry_run:
                actions["created"].append(action)
            else:
                action["reason"] = "Jira create returned no issue key. See payload._jira_create_error."
                actions["create_failed"].append(action)
            continue

        update_fields = build_update_fields(issue, full_record)
        if update_fields:
            payload = update_jira_issue_fields(jira_base_url, issue.get("key"), jira_email, jira_api_token, update_fields, dry_run)
            actions["updated"].append({
                "issueKey": issue.get("key"),
                "adminId": get_admin_id_from_record(full_record),
                "changeKey": full_record.get("changeKey"),
                "title": full_record.get("title"),
                "source": full_record.get("_source"),
                "fields": update_fields,
                "payload": payload,
            })
        else:
            actions["skipped"].append({
                "issueKey": issue.get("key"),
                "adminId": get_admin_id_from_record(full_record),
                "changeKey": full_record.get("changeKey"),
                "title": full_record.get("title"),
                "source": full_record.get("_source"),
                "reason": "No create/update needed",
            })

    # Issue-first reconciliation: existing issues that did not appear in the source-first loop.
    issue_first_reviewed = 0
    issue_first_updated = 0
    for issue in existing_issues:
        issue_key = str(issue.get("key") or "")
        if not issue_key or issue_key in processed_issue_keys:
            continue
        issue_first_reviewed += 1
        fields = issue.get("fields", {})
        probe = {
            "id": normalize_single_option_value(field_value(fields, CF_ADMIN_ID)) or field_value(fields, CF_ADMIN_ID),
            "adminId": normalize_single_option_value(field_value(fields, CF_ADMIN_ID)) or field_value(fields, CF_ADMIN_ID),
            "changeKey": normalize_single_option_value(field_value(fields, CF_CHANGEKEY)) or field_value(fields, CF_CHANGEKEY),
            "title": re.sub(r"^\[[^\]]+\]\s*", "", str(fields.get("summary") or "")).strip(),
            "_source": list(get_existing_source_set(fields)),
        }
        related_private = find_related_private_record(probe, private_indexes)
        related_community = find_related_community_record(probe, community_indexes)
        if not related_private and not related_community:
            continue
        base = related_private or related_community or probe
        full_record = enrich_record(base, private_base_by_id, private_indexes, community_indexes, org_id, private_headers)
        update_fields = build_update_fields(issue, full_record)
        if update_fields:
            payload = update_jira_issue_fields(jira_base_url, issue_key, jira_email, jira_api_token, update_fields, dry_run)
            actions["updated"].append({
                "issueKey": issue_key,
                "adminId": get_admin_id_from_record(full_record),
                "title": full_record.get("title") or fields.get("summary"),
                "source": full_record.get("_source"),
                "fields": update_fields,
                "payload": payload,
                "issueFirstReconciliation": True,
            })
            issue_first_updated += 1

    actions["metadata"]["issue_first_reviewed"] = issue_first_reviewed
    actions["metadata"]["issue_first_updated"] = issue_first_updated

    save_json(actions_output, actions)
    print(f"\nAction summary saved at: {actions_output}")
    print(f"Created: {len(actions['created'])}")
    print(f"Updated: {len(actions['updated'])}")
    print(f"Skipped: {len(actions['skipped'])}")
    print(f"Create failures: {len(actions['create_failed'])}")


if __name__ == "__main__":
    main()
