"""Screenshot tool for capturing screen."""

import json
import subprocess
import tempfile
import base64
import platform
from pathlib import Path
from typing import Any

from flowly.agent.tools.base import Tool


class ScreenshotTool(Tool):
    """Tool for capturing screenshots."""

    name = "screenshot"
    description = "Capture a screenshot of the screen. Returns base64 encoded image or saves to file."

    parameters = {
        "type": "object",
        "properties": {
            "output_path": {
                "type": "string",
                "description": "Optional path to save the screenshot. If not provided, returns base64.",
            },
            "region": {
                "type": "object",
                "description": "Optional region to capture: {x, y, width, height}",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
            },
        },
        "required": [],
    }

    async def execute(self, output_path: str | None = None, region: dict | None = None, **kwargs) -> str:
        """Capture a screenshot."""
        system = platform.system()

        # Create temp file if no output path
        if output_path:
            filepath = Path(output_path)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            filepath = Path(tmp.name)
            tmp.close()

        try:
            if system == "Darwin":  # macOS
                cmd = ["screencapture", "-x"]
                if region:
                    cmd.extend(["-R", f"{region['x']},{region['y']},{region['width']},{region['height']}"])
                cmd.append(str(filepath))
                subprocess.run(cmd, check=True)

            elif system == "Linux":
                # Try gnome-screenshot first, then scrot
                if region:
                    cmd = ["gnome-screenshot", "-a", "-f", str(filepath)]
                else:
                    cmd = ["gnome-screenshot", "-f", str(filepath)]
                try:
                    subprocess.run(cmd, check=True)
                except FileNotFoundError:
                    # Fall back to scrot
                    cmd = ["scrot", str(filepath)]
                    subprocess.run(cmd, check=True)

            elif system == "Windows":
                # Use PowerShell for Windows screenshot
                ps_script = f'''
                Add-Type -AssemblyName System.Windows.Forms
                $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
                $bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
                $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
                $graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
                $bitmap.Save("{filepath}")
                '''
                subprocess.run(["powershell", "-Command", ps_script], check=True)
            else:
                return json.dumps({"error": f"Unsupported platform: {system}"})

            # Read and encode if no output path was specified
            if not output_path:
                with open(filepath, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode("utf-8")
                filepath.unlink()  # Clean up temp file
                return json.dumps({
                    "success": True,
                    "base64": image_data,
                    "format": "png",
                })
            else:
                return json.dumps({
                    "success": True,
                    "path": str(filepath),
                })

        except subprocess.CalledProcessError as e:
            return json.dumps({"error": f"Screenshot failed: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
