- we have two loaders file loader and list loaders
- make sure we have a loader for textlike files where we chunk
- we have a list loader for csv json ,
- we have formatted prompt
- we have side output
- we have tool calling
- we have dispatch within prompt
- we have importing prompt
- we have return source and some keys retrin collection and source context 
- we have side collection


agent-actions/
├── agent_actions_core/
│   ├── core/
│   ├── processors/
│   ├── vendors/
│   └── __init__.py
├── agent_actions_cli/
│   ├── commands/
│   └── __init__.py
├── agent_actions_web/
│   ├── static/
│   ├── templates/
│   └── __init__.py
├── config/
│   ├── default_config.yml
│   └── agent_actions.yml
├── docs/
│   └── web_interface/
├── tests/
│   ├── unit/
│   └── integration/
├── setup.py
├── requirements.txt
├── README.md
├── MANIFEST.in
└── Makefile





* we had a situation where we had code objects in json and need to load the source along side them into staging, what we did was to create the code and ensure they had guid and we used tooling as the first to extract



- gemini and cohere usses the gemini schema format
- Openai has its own schema formatclear
