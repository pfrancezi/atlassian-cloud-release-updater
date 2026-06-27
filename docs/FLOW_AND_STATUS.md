# Flow and Status Guide

This document explains how the Atlassian Cloud Release Updater collects source data, merges records, creates or updates Jira issues, and handles lifecycle fields.

Portuguese version: [FLUXO_E_STATUS.md](FLUXO_E_STATUS.md)

## Source model

The marketplace-ready version uses two sources:

| Source | Internal label | Required? | How it is collected | Main purpose |
|---|---|---:|---|---|
| Atlassian Admin private source | `Private` | No | Customer-provided `admin.atlassian.com` session cookie | Private/admin lifecycle metadata, release dates, site release status, delayability details, and detailed change content. |
| Atlassian Community Release Notes | `Community` | Yes | Public Community API | Public release-note visibility, Community status/type, first publication date, and public detailed content. |

The legacy Confluence weekly blog parser was removed. The active flow no longer uses a public blog URL, Product Section, Week Title, Week URL, or Rollout Flags field.

## Execution flow

```text
Start
  ↓
Read local configuration and Jira connection values
  ↓
Optionally collect the private Admin source
  ↓
Collect the public Community Release Notes source
  ↓
Normalize both source payloads into a common record shape
  ↓
Merge records by Atlassian/Admin ID, change key when available, or normalized title
  ↓
Check/create missing Jira select-list options when enabled
  ↓
Read existing Jira issues from the configured project
  ↓
For each merged source record:
    Find matching Jira issue by Admin ID, change key, or title
    If no issue exists and creation is enabled:
        Create a new Jira issue
    If an issue exists:
        Build an update payload only for fields that need changes
  ↓
Issue-first reconciliation:
    Review existing Jira issues that were not processed in the source-first loop
    Enrich them if they now appear in one of the sources
  ↓
Write the actions JSON file
End
```

## Matching logic

The script tries to avoid duplicates by matching in this order:

1. `CF_ADMIN_ID`, the opaque Atlassian/Admin/Community change ID.
2. `CF_CHANGEKEY`, when a provider/public key exists.
3. Normalized title, with the summary token removed.

Recommended practice: configure `CF_ADMIN_ID`. It is the most stable matching field for this utility.

## New issue creation behavior

When a record does not match an existing issue and creation is enabled, the script creates a Jira issue with:

| Jira area | Behavior |
|---|---|
| Summary | Uses `[changeKey] Title` when a change key exists, otherwise `[adminId] Title`, otherwise just the title. |
| Description | Generated in Atlassian Document Format from available detailed source content. |
| Source | Set to `Private`, `Community`, or both, depending on where the change was found. |
| Products | Merged and mapped technical product tags. |
| Change Status | Set to `NEW THIS WEEK` only when the new issue has the Private source. |
| Community Status | Set to `NEW THIS WEEK` when the new issue has Community status. |
| Community dates | Filled from Community `firstPublishedAt` and release start fields when available. |
| Private dates | Filled from Admin private metadata when available. |

## Status fields and their meaning

The scripts intentionally keep private/admin lifecycle status separate from Community lifecycle status.

### Change Status

`CF_CHANGE_STATUS` represents the private Atlassian Admin lifecycle status only.

| Value | Meaning in this utility | Source |
|---|---|---|
| `NEW THIS WEEK` | The change was newly created from the Private source or appeared in the Private source for the first time for an existing issue. This is a tracking marker, not necessarily the real Atlassian lifecycle status. | Script-generated |
| `COMING_SOON` | The private Admin source says the change is coming soon. | Private |
| `ROLLING_OUT` | The private Admin source says the change is rolling out. | Private |
| `GENERALLY_AVAILABLE` | The private Admin source says the change is generally available or release-complete. | Private |
| `PLANNED` | The private Admin source says the change is planned. | Private |
| `EXPERIMENT` | The private Admin source classifies the change as an experiment. | Private |
| `DEPRECATED` | The private Admin source marks the change as deprecated. | Private |
| `ANNOUNCEMENT` | The private Admin source classifies the change as an announcement. | Private |

`Change Status` is not derived from Community status. This prevents the public release note lifecycle from overwriting the private/admin lifecycle.

### Community Status

`CF_COMMUNITY_STATUS` represents the lifecycle status from Atlassian Community Release Notes. It is designed as a single-select field because only one current public lifecycle status should be stored at a time.

| Value | Meaning in this utility | Source |
|---|---|---|
| `NEW THIS WEEK` | The change was newly created from Community or appeared in Community for the first time for an existing issue. This is the public visibility marker that replaced the old Rollout Flags field. | Script-generated |
| API status value | The status returned by the Community API after the first-week marker is cleared on a later run. | Community |

The exact Community status values depend on what the Community API returns. The script normalizes common lifecycle values, for example `COMING_SOON`, `ROLLING_OUT`, and `GENERALLY_AVAILABLE`.

## How `NEW THIS WEEK` is updated

### First-appearance rules

| Scenario | Result |
|---|---|
| New issue created from Private | `Change Status = NEW THIS WEEK`. |
| New issue created from Community | `Community Status = NEW THIS WEEK`. |
| Existing issue appears in Private for the first time | Adds `Private` to Source and sets `Change Status = NEW THIS WEEK`. |
| Existing issue appears in Community for the first time | Adds `Community` to Source, sets `Community Status = NEW THIS WEEK`, fills Community dates, and refreshes the description. |

### Following-run rules

On a later execution, when the issue already has `NEW THIS WEEK`, the script replaces the marker with the real status from the same source when that status exists.

| Field | Later behavior |
|---|---|
| `Change Status` | Replaced with the real Private status when available. |
| `Community Status` | Replaced with the real Community status when available. |

Example for Community:

```text
Run 1: item appears in Community for the first time
  → Community Status = NEW THIS WEEK

Run 2: same item is collected again from Community
  → Community Status = ROLLING_OUT, COMING_SOON, GENERALLY_AVAILABLE, or another status returned by the API
```

## Date behavior

The two scripts differ only in how they format date fields for Jira.

| Script | Date mode | Payload example |
|---|---|---|
| `weekly_release_updater_jpd.py` | JPD date-range string | `{"start":"2026-06-22","end":"2026-06-22"}` |
| `weekly_release_updater_jira_software.py` | Plain Jira date | `2026-06-22` |

Community week dates are calculated from `communityFirstPublishedAt`:

| Field | Calculation |
|---|---|
| `CF_COMMUNITY_FIRST_PUBLISHED` | Date from Community `firstPublishedAt`. |
| `CF_COMMUNITY_WEEK_START` | Monday of the same week. |
| `CF_COMMUNITY_WEEK_END` | Sunday of the same week. |

Example: if `firstPublishedAt` is `2026-06-24`, the week start is `2026-06-22` and the week end is `2026-06-28`.

## Where the Jira description comes from

The issue description is generated in Atlassian Document Format from the richest detailed source payload available.

The script tries to add these sections when they exist:

| Jira description section | Source field |
|---|---|
| Summary | `summary` |
| Key changes | `keyChanges` |
| Benefits | `benefitsList` |
| How to get started | `getStarted` |
| Reason for change | `reasonForChange` |
| Prepare for change | `prepareForChange` |
| Informed about change | `informedAboutChange` |
| Affected by change | `affectedByChange` |

The description also adds:

- `Sources: Private, Community` when sources are known.
- `Atlassian change id: ...` when an Admin/Community ID exists.
- A note when a detail request fails but the source record is still preserved.

The description is updated when a new source is added to an existing issue, as long as `UPDATE_DESCRIPTION_ON_SOURCE_ADDED` is enabled.

## Field update principles

The script builds small update payloads. It does not rewrite every field on every run.

It updates a field when:

- the field is configured in the script;
- the source record has a desired value;
- the current Jira value is empty or different;
- or a new source appeared and the issue needs enrichment.

Optional fields are ignored when the corresponding `CF_*` constant is empty.

## Option creation

When `AUTO_CREATE_FIELD_OPTIONS = True`, the script checks configured select and multi-select fields and creates missing options before trying to create or update issues.

This applies to fields such as Source, Products, Change Status, Change Type, Site Status, Community Status, Community Change Type, Is Delayable, and Is Delayed. Community Status should be configured as single-select, while Community Change Type can remain multi-select.

## Actions log

At the end of each execution, the script writes an actions JSON file containing:

| Section | Meaning |
|---|---|
| `created` | Issues created or creation payloads in dry-run. |
| `updated` | Issues updated or update payloads in dry-run. |
| `skipped` | Records where no create/update was needed or creation was disabled. |
| `create_failed` | Records where Jira issue creation failed. |
| `metadata` | Execution summary, source counts, dry-run flag, timestamp, and date mode. |

The actions log is useful for audit and troubleshooting. It should not contain API tokens or cookies.
