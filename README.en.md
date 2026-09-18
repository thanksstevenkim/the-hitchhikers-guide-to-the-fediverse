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
| Discovery seeds | <https://thanksstevenkim.github.io/the-hitchhikers-guide-to-the-fediverse/data/instances.json> | Manually maintained peer-discovery starting points and ecosystem coverage anchors |

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
      "deployment_kind": "federated_service",
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
| `deployment_kind` | string | Operational role: `federated_service`, `activitypub_enabled_site`, `federation_infrastructure`, or `unknown` |
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
      "deployment_kind": "federated_service",
      "members": ["hometown"]
    },
    "unknown": {
      "type": "fallback",
      "deployment_kind": "unknown",
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

`deployment_kind` answers a different question from software lineage or function:

- `federated_service`: software deployed primarily as a federated service
- `activitypub_enabled_site`: general publishing software participating through ActivityPub, currently WordPress and Ghost
- `federation_infrastructure`: bridges, relays, and supporting infrastructure
- `unknown`: software whose operational role has not been classified

This distinction does not rank one participant as more "proper" than another. It allows consumers to include all verified ActivityPub hosts or report publishing/CMS deployments separately.

When a repository explicitly identifies itself as a fork of Mastodon, Misskey, Pleroma, or another maintained lineage, that family takes precedence over a functional category. API compatibility or multi-protocol support alone does not establish lineage.

## Data lifecycle

`instances.json` contains discovery seeds, while `monitored_instances.json` is the persistent canonical-host registry. The size of the monitored registry is a count of collection targets, not a count of currently healthy hosts. The collector checks that registry, writes verified records to `stats.ok.json`, and retains failures locally in `stats.bad.json` for diagnosis and recovery checks.

Optional peer discovery applies exact-host and confirmed domain-zone blocklist rules, domain-pattern heuristics, and statistical anomaly checks before manual review. A TLD alone never causes a candidate to be rejected. Individual abusive servers belong in `exact_hosts`; a domain known to generate abusive hosts for the same purpose belongs in `domain_suffixes`. Suffix matching respects DNS label boundaries.

The tracked rules live in `data/spam_domain_blocklist.json`. `--blocklist <file>` replaces that default for a local run. A historical `spam_filtered.log.json` can be passed directly as input to re-evaluate candidates after a rule change. Use separate output paths; the script rejects attempts to overwrite its input.

```bash
python scripts/filter_spam.py \
  --input data/spam_filtered.log.json \
  --output /tmp/recheck_candidates.json \
  --log /tmp/recheck_filtered.log.json

# Review both files, then collect only the candidates that passed.
python scripts/fetch_stats.py --input /tmp/recheck_candidates.json
```

### Coverage limits and seed diversity

This dataset is not a complete census of the Fediverse. It is a sample of servers that could be discovered from manually maintained seeds through public peer relationships and public APIs, and whose responses could be verified. Servers that do not publish peer lists, are not connected to the current seeds, are temporarily unavailable, or restrict access may be absent. Observed software shares and server-size distributions therefore must not be interpreted as global Fediverse market share or as the proportion of personal servers.

The site labels the broad count as **verified ActivityPub hosts**. It separately reports hosts classified as `activitypub_enabled_site`, so WordPress and Ghost publishing sites are not silently presented as conventional dedicated Fediverse services. A host with `users_total = 1` is described only as a **host reporting exactly one user**. User totals are software-reported, are not available or comparable for every implementation, and do not prove that a host is a personal server.

Seeds have two roles. A `discovery` seed is a starting point for a peer path supported by the collector. A `coverage` seed ensures that a software lineage or use case is checked directly even when it does not expose a usable peer list. The table below tracks priority coverage rather than every entry in the taxonomy. Selecting a server as a seed is not an endorsement or guarantee of its moderation or operating policies.

| Use case | Software or lineage | Representative seed | Role | Status |
| --- | --- | --- | --- | --- |
| Microblogging | Mastodon family | `mastodon.social` and 7 others | discovery | Existing |
| Microblogging | Misskey family | `misskey.io`, `aoharu.place` | discovery | Existing |
| Microblogging | Pleroma family (Akkoma) | `fe.disroot.org` | coverage | Added in this phase |
| Lightweight microblogging | GoToSocial | — | coverage | Gap |
| Forums and discussion | Lemmy | `lemmy.ml` | coverage | Existing |
| Photos | Pixelfed | `pixelfed.social` | coverage | Added in this phase |
| Video | PeerTube | `framatube.org` | coverage | Added in this phase |
| Reading and reviews | BookWyrm | `bookwyrm.it` | coverage | Added in this phase |
| Events and groups | Mobilizon | `mobilizon.fr` | coverage | Added in this phase |
| General social networking | Friendica | `friendica.world` | coverage | Added in this phase |
| Hubs and publishing | Hubzilla | `hub.netzgemeinde.eu` | coverage | Added in this phase |
| Long-form blogging | WriteFreely | `write.as` | coverage | Added in this phase |
| Audio and music | Funkwhale | — | coverage | Gap |
| Software forges | Forgejo | — | coverage | Gap |

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

To reproduce a network failure or a local security-tool block without scanning the full registry, select a zero-based slice after canonical sorting and deduplication. `--trace-hosts` logs `TRACE START` and `TRACE END` around each target; use one worker when the final started host must be unambiguous.

```bash
python -u scripts/fetch_stats.py \
  --discover-peers \
  --start-index 1000 \
  --limit 50 \
  --workers 1 \
  --trace-hosts \
  2>&1 | tee fetch-trace.log
```

Range and trace runs write ordinary collection results and checkpoints. Use `--data-dir` with an isolated copy when the tracked data must remain unchanged. With `--input`, range selection happens after known hosts are excluded and the remaining canonical hosts are sorted and deduplicated.

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
| `scripts/filter_spam.py` | Filter peer candidates using exact-host and domain-suffix rules, domain heuristics, and anomaly checks |
| `scripts/validate_data.py` | Validate tracked and generated data invariants |

## Privacy and license

The project collects public server metadata and does not intentionally collect personal information. It is licensed under the [MIT License](./LICENSE).
