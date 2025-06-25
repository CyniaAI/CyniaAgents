from subprocess import Popen, PIPE, STDOUT
import shutil
import locale
import queue

from log_writer import logger


def build_plugin(artifact_name, path=False, output_queue: queue.Queue = None) -> str:
    project_path = f"codes/{artifact_name}" if not path else artifact_name
    mvn_exec = shutil.which("mvn") or shutil.which("mvn.cmd")
    sys_enc = locale.getpreferredencoding(False)
    if not mvn_exec:
        raise FileNotFoundError("Could not find 'mvn' executable. Please ensure Maven is installed and available in your PATH.")

    build_command = [
        mvn_exec,
        "-V",
        "-B",
        "clean",
        "package",
        "--file",
        "pom.xml",
    ]

    process = Popen(
        build_command,
        stdout=PIPE,
        stderr=STDOUT,
        cwd=project_path,
        text=True,
        encoding=sys_enc,
        errors="replace",
        shell=False
    )

    output = ""
    for line in process.stdout:
        clean = line.rstrip()
        logger(f"building -> {clean}")
        output += clean + "\n"
        
        # 将输出发送到队列（如果提供了队列）
        if output_queue:
            output_queue.put(clean)

    process.wait()
    return output


if __name__ == "__main__":
    result = build_plugin("Demo4")
    print(result)
    print(type(result))
