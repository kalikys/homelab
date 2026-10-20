---
title: Example post that proves the blog pipeline works end to end
description: A draft used to check headings, lists, code, tables, quotes and links. Files starting with an underscore are never published.
date: 2026-10-21
updated: 2026-10-21
tags: [kubernetes, gitlab-ci, terraform]
lang: en
---

Intro paragraph with **bold**, *italic*, `inline <code> & stuff` and a [link to the CV](/#cases) plus an [external link](https://kubernetes.io/docs/).

## Why this exists

Writers deliver Markdown. The generator turns it into a static page.

## Steps

1. Write `content/blog/<slug>.md`.
2. Run the build.
   It also updates the sitemap.
3. Commit the output.

- bullet one
- bullet two with `code`

## Code

```yaml
stages: [scan]
trivy:
  stage: scan
  script:
    - trivy fs --exit-code 1 --severity HIGH,CRITICAL .
```

```
plain <fence> & no language
```

## Table

| Tool | Stage | Blocks merge |
|------|:-----:|-------------:|
| Gitleaks | pre-build | yes |
| Trivy | scan | yes |

> A quote with **emphasis**.
> Second line.

### A smaller heading

The end. <script>alert(1)</script> stays text.
