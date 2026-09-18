# The Hitchhiker's Guide to the Fediverse

[한국어 README](./README.md)

A static, bilingual directory of verified Fediverse instances. The project collects public NodeInfo and platform metadata, validates it, and publishes searchable instance data through GitHub Pages.

The repository also publishes a machine-readable software taxonomy and registry for consumers that need normalized Fediverse software identifiers.

## Public site

<https://thanksstevenkim.github.io/the-hitchhikers-guide-to-the-fediverse/>

## Public data URLs

The Pages URLs below are updated by the scheduled or manually dispatched deployment workflow. Immediately after a repository merge, they may continue serving the previous deployment until that workflow finishes.

| Dataset | Public URL | Purpose |
| --- | --- | --- |
| Healthy instance statistics | <https://thanksstevenkim.github.io/the-hitchhikers-guide-to-the-fediverse/data/stats.ok.json> | Verified instances currently displayed by the site |
| Software taxonomy | <https://thanksstevenkim.github.io/the-hitchhikers-guide-to-the-fediverse/data/software_taxonomy.json> | Maintained family and functional classifications |
| Software registry | <https://thanksstevenkim.github.io/the-hitchhikers-guide-to-the-fediverse/data/software_registry.json> | Generated software-level observations joined to the taxonomy |
| Discovery seeds | <https://thanksstevenkim.github.io/the-hitchhikers-guide-to-the-fediverse/data/instances.json> | Manually maintained starting points for peer discovery |

These files are static JSON resources. Consumers should check `schema_version` before processing them and tolerate additive fields within the same schema version.

The same tracked files are also available directly from the default branch under `https://raw.githubusercontent.com/thanksstevenkim/the-hitchhikers-guide-to-the-fediverse/main/data/`.

## Software registry

`software_registry.json` is generated from the current healthy-instance snapshot and `software_taxonomy.json`. It contains taxonomy entries even when they have no currently healthy instance, along with newly observed software that has not yet been classified.

```json
{
  "schema_version": 1,
  "taxonomy_schema_version": 1,
  "dataset_fetched_at": "2026-09-17T23:24:33Z",
  "software_count": 475,
  "software": [
    {
      "software_id": "hometown",
      "group_id": "mastodon",
      "group_type": "family",
      "classification_status": "classified",
      "healthy_instance_count": 94,
      "observed_names": ["hometown"],
      "last_observed_at": "2026-09-17T23:24:33Z"
    }
  ]
}
```

### Top-level fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Registry schema version |
| `taxonomy_schema_version` | integer | Schema version of the taxonomy used to generate the registry |
| `dataset_fetched_at` | string or `null` | Latest observation timestamp in the healthy-instance snapshot |
| `software_count` | integer | Number of objects in `software` |
| `software` | array | Deterministically ordered software entries |

### Software entry fields

| Field | Type | Meaning |
| --- | --- | --- |
| `software_id` | string | Lowercase, hyphen-normalized software identifier |
| `group_id` | string | Taxonomy group assigned to the software |
| `group_type` | string | `family`, `software`, `category`, or `fallback` |
| `classification_status` | string | `classified`, `explicit_unknown`, or `unclassified` |
| `healthy_instance_count` | integer | Unique healthy hosts currently reporting this software ID |
| `observed_names` | array of strings | Reported names ordered by frequency, then case-insensitively |
| `last_observed_at` | string or `null` | Most recent healthy observation for this software ID |

`classified` means the ID maps to a maintained non-fallback taxonomy group. `explicit_unknown` means it is retained in the taxonomy's `unknown` group for later review. `unclassified` means it was observed in healthy statistics but is not present in the maintained taxonomy.

The registry excludes observations without a software name. It also excludes `ap-tombstone`, which is an instance-retirement marker rather than a software implementation.

## Software taxonomy

`software_taxonomy.json` separates maintained classification decisions from UI code. Its top-level structure is:

```json
{
  "schema_version": 1,
  "group_order": ["mastodon", "misskey", "pleroma", "unknown"],
  "groups": {
    "mastodon": {
      "type": "family",
      "members": ["hometown"]
    },
    "unknown": {
      "type": "fallback",
      "members": []
    }
  }
}
```

Group types have the following meanings:

- `family`: a software lineage such as Mastodon, Misskey, or Pleroma
- `software`: a standalone implementation displayed as its own group
- `category`: a functional grouping such as blogs, forums, video, bridges, or relays
- `fallback`: the single `unknown` review group

When a repository explicitly identifies itself as a fork of Mastodon, Misskey, Pleroma, or another maintained lineage, that family takes precedence over a functional category. API compatibility or multi-protocol support alone does not establish lineage.

## Data lifecycle

`instances.json` contains discovery seeds, while `monitored_instances.json` is the persistent canonical-host registry. The collector checks the monitored registry, writes verified records to `stats.ok.json`, and retains failures locally in `stats.bad.json` for diagnosis and recovery checks.

Optional peer discovery applies an exact-host blocklist, domain-pattern heuristics, and statistical anomaly checks before manual review. A TLD alone never causes a candidate to be rejected; confirmed abusive servers should be blocked by their exact host instead.

The scheduled workflow runs daily at 21:00 UTC. It collects into an isolated staging directory, builds `software_registry.json`, validates the complete dataset, promotes validated outputs, commits changed tracked data, and deploys the public Pages artifact.

## Local setup

Python 3.12 is used by CI.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Refresh and validate the data:

```bash
python scripts/fetch_stats.py
python scripts/build_software_registry.py
python scripts/validate_data.py
python scripts/build_software_review_queue.py
```

Generate the registry from another data directory or print it to standard output:

```bash
python scripts/build_software_registry.py --data-dir /path/to/data
python scripts/build_software_registry.py --output -
```

Run the test suite:

```bash
python -m pytest
```

## Main scripts

| Script | Purpose |
| --- | --- |
| `scripts/fetch_stats.py` | Collect and normalize public Fediverse instance metadata |
| `scripts/build_software_registry.py` | Generate the public software registry |
| `scripts/build_software_review_queue.py` | Prioritize unknown and unclassified software for manual review |
| `scripts/filter_spam.py` | Filter peer candidates using an exact blocklist, domain heuristics, and anomaly checks |
| `scripts/validate_data.py` | Validate tracked and generated data invariants |

## Privacy and license

The project collects public server metadata and does not intentionally collect personal information. It is licensed under the [MIT License](./LICENSE).
