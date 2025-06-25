import uuid

import config
import core
import build


def main():
    api_key = config.API_KEY
    base_url = config.BASE_URL
    if not api_key or not base_url:
        raise EnvironmentError("Testing API credentials are not set")

    config.API_KEY = api_key
    config.BASE_URL = base_url
    config.LLM_PROVIDER = "openai"
    config.GENERATION_MODEL = "gpt-4.1-ca"

    core.initialize()

    artifact_name = f"Test{uuid.uuid4().hex[:8]}"
    pkg_id = f"dev.cynia.{uuid.uuid4().hex[:8]}"
    pkg_id_path = "/".join(pkg_id.split(".")) + "/"

    codes = core.askgpt(
        config.SYS_GEN.replace("%ARTIFACT_NAME%", artifact_name).replace("%PKG_ID_LST%", pkg_id_path),
        config.USR_GEN.replace("%DESCRIPTION", "test plugin"),
        config.GENERATION_MODEL,
    )

    core.response_to_action(codes)
    output = build.build_plugin(artifact_name)
    if "BUILD SUCCESS" in output:
        print("CLI test succeeded")
    else:
        print(output)
        raise RuntimeError("Build failed")


if __name__ == "__main__":
    main()
