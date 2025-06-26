import os
import json
import shutil
from dotenv import load_dotenv
from log_writer import logger

# Built-in registry of configuration items.
# Each entry maps the key name to a dictionary containing a description and UI
# hints. Components can extend this dictionary at runtime via
# ``register_config_item``.
CONFIG_ITEMS = {
    "LLM_PROVIDER": {
        "description": "LLM service provider",
        "type": "select",
        "options": ["openai", "anthropic", "google"],
    },
    "API_KEY": {
        "description": "API key for the LLM provider",
        "type": "password",
    },
    "BASE_URL": {"description": "Base URL for the API provider"},
    "GENERATION_MODEL": {"description": "Model used for generation"},
    "FIXING_MODEL": {"description": "Model used for fixing"},
}


def load_config():
    """
    Loads the configuration from the ``.env`` file and ``prompts.json`` file,
    and sets the global variables accordingly.

    If the ``GENERATION_MODEL`` key in the configuration is set to ``gpt-4``,
    the function forces the use of ``gpt-4-turbo-preview`` as the value for this
    key since ``gpt-4`` no longer supports JSON modes.

    Returns:
        None
    """
    # Ensure the .env file exists by copying from the example if necessary
    if not os.path.exists('.env') and os.path.exists('.env.example'):
        shutil.copy('.env.example', '.env')

    # Load environment variables from .env file
    load_dotenv()
    
    # Load configuration from .env file
    for key, meta in CONFIG_ITEMS.items():
        default = meta.get("default", "")
        value = os.getenv(key, default)
        globals()[key] = value
        logger(
            f"config: {key} -> {value if key != 'API_KEY' else '********'}"
        )
      # Load prompts from prompts.json file
    try:
        with open('prompts.json', 'r', encoding='utf-8') as f:
            prompts = json.load(f)
            
        # Configuration keys that should be loaded from prompts.json
        prompt_config_keys = ['SYS_GEN', 'USR_GEN', 'SYS_EDIT', 'USR_EDIT']
        
        for key in prompt_config_keys:
            value = prompts.get(key, '')
            # Handle both string and array formats
            if isinstance(value, list):
                value = '\n'.join(value)
            globals()[key] = value
            logger(f"prompt: {key} -> loaded from prompts.json")
            
    except FileNotFoundError:
        logger("Warning: prompts.json file not found. Prompt configurations not loaded.")
        # Set default empty values for prompt keys
        for key in ['SYS_GEN', 'USR_GEN', 'SYS_EDIT', 'USR_EDIT']:
            globals()[key] = ''
    except json.JSONDecodeError as e:
        logger(f"Error: Failed to parse prompts.json: {e}")
        # Set default empty values for prompt keys
        for key in ['SYS_GEN', 'USR_GEN', 'SYS_EDIT', 'USR_EDIT']:
            globals()[key] = ''


def edit_config(key, value):
    """
    Edits the config file (.env) or prompts file (prompts.json).

    Args:
        key (str): The key to edit.
        value (str): The value to set.

    Returns:
        bool: True
    """
    # Check if this is a prompt-related key
    prompt_keys = ['SYS_GEN', 'USR_GEN', 'SYS_EDIT', 'USR_EDIT']
    
    if key in prompt_keys:
        # Edit prompts.json file
        prompts_file_path = 'prompts.json'
        
        try:
            # Read current prompts.json file content
            with open(prompts_file_path, "r", encoding='utf-8') as f:
                prompts = json.load(f)
        except FileNotFoundError:
            # If prompts.json doesn't exist, create it
            prompts = {}
        except json.JSONDecodeError:
            # If prompts.json is invalid, reset it
            prompts = {}
          # Update the key-value pair
        # Convert string to array format for better readability
        if isinstance(value, str) and '\n' in value:
            prompts[key] = value.split('\n')
        else:
            prompts[key] = str(value)
        
        # Write back to prompts.json file
        with open(prompts_file_path, "w", encoding='utf-8') as f:
            json.dump(prompts, f, indent=2, ensure_ascii=False)
        
        # Update the global variable
        globals()[key] = str(value)
        
    else:
        # Edit .env file for non-prompt keys
        env_file_path = '.env'
        
        # Read current .env file content
        env_lines = []
        try:
            with open(env_file_path, "r", encoding='utf-8') as f:
                env_lines = f.readlines()
        except FileNotFoundError:
            # If .env doesn't exist, create it
            pass
        
        # Update or add the key-value pair
        key_found = False
        for i, line in enumerate(env_lines):
            if line.strip().startswith(f"{key}="):
                if isinstance(value, bool):
                    write_value = "true" if value else "false"
                else:
                    write_value = str(value)
                env_lines[i] = f"{key}={write_value}\n"
                key_found = True
                break
        
        # If key wasn't found, add it
        if not key_found:
            if isinstance(value, bool):
                write_value = "true" if value else "false"
            else:
                write_value = str(value)
            env_lines.append(f"{key}={write_value}\n")
        
        # Write back to .env file
        with open(env_file_path, "w", encoding='utf-8') as f:
            f.writelines(env_lines)
        
        # Update the global variable
        globals()[key] = str(value)

    return True


def register_config_item(
    key: str,
    description: str,
    default: str = "",
    input_type: str = "text",
    options: list | None = None,
) -> None:
    """Register a new configuration item.

    Components can call this function to expose additional configuration values
    in the UI.

    Args:
        key: The name of the configuration entry.
        description: Description displayed in the configuration center.
        default: Default value used if the key is missing from ``.env``.
        input_type: The type of UI input (``text``, ``password`` or ``select``).
        options: Options for ``select`` inputs.
    """
    CONFIG_ITEMS[key] = {
        "description": description,
        "type": input_type,
    }
    if options:
        CONFIG_ITEMS[key]["options"] = options
    if default:
        CONFIG_ITEMS[key]["default"] = default
    value = os.getenv(key, default)
    globals()[key] = value


load_config()
