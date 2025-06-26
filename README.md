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

## License
Licensed under the Apache 2.0 License.
