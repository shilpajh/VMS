# Smart VMS — Project Memory

Append-only log, one entry per completed story, written by `/document-story` (see step 3).
Future stories' GATHER step reads the last 5-10 entries here before touching anything else —
this is the cheapest context a story can get, cheaper than re-reading old specs or diffs.
Keep entries to 6-10 lines each; a rambling entry defeats the purpose.

<!-- Entries below this line, most recent last. -->
