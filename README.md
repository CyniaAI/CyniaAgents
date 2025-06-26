# Cynia Agents

Cynia Agents is a lightweight framework for running generative agents through a Streamlit interface.  
Generation logic lives in installable **components** which can be added or removed without modifying the UI.

The repository ships with only a simple example component.  Complex generators such as the Bukkit plugin agent can be distributed separately and dropped into the `components` folder.

## Quick Start

1. Install the Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the UI:
   ```bash
   streamlit run web.py
   ```
   The application will create a `.env` file from `.env.example` if it does not exist.
3. Configure your API keys and choose an LLM provider from the **Configuration Center** page in the sidebar.
4. Use the **Component Center** to enable or disable installed components.

## Adding Components
See [COMPONENT_DEVELOPMENT.md](COMPONENT_DEVELOPMENT.md) for information on building your own generators.

## Using the LLM Helper
Components can talk to the configured language model through the `LLM` class in `utils.py`.
Create an instance and call `ask()` for a single response or start a `Conversation` for multi-turn chat.

```python
from utils import LLM

llm = LLM()
reply = llm.ask("You are a helpful assistant.", "Hello")
```
To hold a conversation create a `Conversation` instance and call `send()`:

```python
conv = llm.create_conversation("You are a helpful assistant.")
reply = conv.send("Hello")
```
The conversation history is available via ``conv.history``.

The constructor accepts optional `provider`, `api_key`, `base_url` and `model_name` parameters, falling back to configuration values.


## License
Licensed under the Apache 2.0 License.
