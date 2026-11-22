import json
from government_assistant.config import settings
from government_assistant.storage import Repository
r=Repository(settings.db_path)
print(json.dumps({"schemes":len(r.schemes()),"chunks":len(r.chunks()),"index_manifest":r.manifest()},indent=2))
