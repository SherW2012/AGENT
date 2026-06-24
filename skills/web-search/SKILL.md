---
name: web-search
description: Search public web sources for current external knowledge while keeping patient data, secrets, internal paths, and private code out of queries.
display_name: Web Search
short_description: Background current-knowledge search.
visibility: background
enabled: true
---

# Web Search

Use this background skill when the user needs current public information: latest papers, standards, APIs, regulations, release notes, prices, dates, or any claim that may have changed after the model's training data.

Default behavior:

- In `auto` mode, search automatically for current public facts unless the user says not to use the web.
- In `ask` mode, every web search is routed through human approval.
- In `off` mode, no web-search tool is exposed.
- Never put patient identifiers, API keys, internal paths, private hostnames, private code, or company-confidential details in a search query.
- If the user asks for a sensitive lookup, sanitize the query into generic public terms or ask for approval before searching.
- Cite volatile facts with source title and URL, but integrate citations naturally. Avoid boilerplate such as "according to search results" unless it is needed to avoid overclaiming.
