#!/usr/bin/env python3

import adsk.core
import adsk.fusion
import os
import sys
import traceback
import threading
import time
import json
import asyncio
from pathlib import Path

from ..lib import fusionAddInUtils as futil

# Global variables
app = adsk.core.Application.get()
ui = app.userInterface
server_thread = None
server_running = False
message_command_handlers = []  # Store command handlers to prevent garbage collection

# Initialize the global handlers list
handlers = []

# Root path: the MCPserve add-in directory (parent of 'commands/')
ADDIN_ROOT = Path(os.path.dirname(os.path.dirname(__file__)))
COMM_DIR = ADDIN_ROOT / "mcp_comm"


def _ensure_comm_dir():
    """Ensure the communication directory exists and return its path."""
    COMM_DIR.mkdir(parents=True, exist_ok=True)
    return COMM_DIR


def _debug_log(filename, message):
    """Write a debug message to a file in the comm directory."""
    try:
        comm = _ensure_comm_dir()
        with open(comm / filename, "a") as f:
            f.write(f"{message} at {time.ctime()}\n")
    except Exception:
        pass


# Function to check if MCP package is installed
def check_mcp_installed():
    missing_packages = []

    try:
        import mcp
        print(f"Found MCP package at: {mcp.__file__}")
    except ImportError as e:
        print(f"Error importing MCP package: {str(e)}")
        missing_packages.append("mcp[cli]")

    try:
        import uvicorn
        print(f"Found uvicorn package at: {uvicorn.__file__}")
    except ImportError as e:
        print(f"Error importing uvicorn package: {str(e)}")
        missing_packages.append("uvicorn")

    if missing_packages:
        print(f"Missing required packages: {', '.join(missing_packages)}")
        return False

    return True


# Function to run MCP server
def run_mcp_server():
    try:
        # Import required MCP modules
        import mcp
        from mcp.server.fastmcp import FastMCP
        import uvicorn

        comm_dir = _ensure_comm_dir()

        # Write diagnostic info
        diagnostic_log = comm_dir / "mcp_server_diagnostics.log"
        with open(diagnostic_log, "w") as f:
            f.write(f"MCP Server Diagnostics - {time.ctime()}\n\n")
            f.write(f"Server URL: http://127.0.0.1:3000/sse\n")
            f.write(f"Add-in root: {ADDIN_ROOT}\n")
            f.write(f"Communication directory: {comm_dir}\n\n")
            f.write(f"Python version: {sys.version}\n\n")

            try:
                mcp_version = getattr(mcp, "__version__", "Unknown")
                f.write(f"MCP Version: {mcp_version}\n\n")
            except Exception:
                f.write("MCP Version: Unable to determine\n\n")

        print("Creating FastMCP server instance...")
        # Create the MCP server
        fusion_mcp = FastMCP("Fusion 360 MCP Server")

        print("Registering resources...")
        # Define resources
        @fusion_mcp.resource("fusion://active-document-info")
        def get_active_document_info():
            """Get information about the active document in Fusion 360."""
            try:
                doc = app.activeDocument
                if doc:
                    path = "Unsaved"
                    try:
                        if hasattr(doc, 'dataFile') and doc.dataFile:
                            path = doc.dataFile.name
                    except Exception:
                        pass

                    return {
                        "name": doc.name,
                        "path": path,
                        "type": str(doc.documentType)
                    }
                else:
                    return {"error": "No active document"}
            except Exception as e:
                return {"error": str(e) + "\n" + traceback.format_exc()}

        @fusion_mcp.resource("fusion://design-structure")
        def get_design_structure():
            """Get the structure of the active design in Fusion 360."""
            try:
                doc = app.activeDocument
                if not doc:
                    return {"error": "No active document"}

                if str(doc.documentType) != "FusionDesignDocumentType":
                    return {"error": "Not a Fusion design document"}

                design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
                if not design:
                    return {"error": "No design in document"}

                root_comp = design.rootComponent

                def get_component_data(component):
                    data = {
                        "name": component.name,
                        "bodies": [body.name for body in component.bodies],
                        "sketches": [sketch.name for sketch in component.sketches],
                        "occurrences": []
                    }

                    for occurrence in component.occurrences:
                        data["occurrences"].append({
                            "name": occurrence.name,
                            "component": occurrence.component.name
                        })

                    return data

                return {
                    "design_name": design.name,
                    "root_component": get_component_data(root_comp)
                }
            except Exception as e:
                return {"error": str(e) + "\n" + traceback.format_exc()}

        @fusion_mcp.resource("fusion://parameters")
        def get_parameters():
            """Get the parameters of the active design in Fusion 360."""
            try:
                doc = app.activeDocument
                if not doc:
                    return {"error": "No active document"}

                if str(doc.documentType) != "FusionDesignDocumentType":
                    return {"error": "Not a Fusion design document"}

                design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
                if not design:
                    return {"error": "No design in document"}

                params = []
                for param in design.allParameters:
                    params.append({
                        "name": param.name,
                        "value": param.value,
                        "expression": param.expression,
                        "unit": param.unit,
                        "comment": param.comment
                    })

                return {"parameters": params}
            except Exception as e:
                return {"error": str(e) + "\n" + traceback.format_exc()}

        print("Registering tools...")

        # message_box stays here — it needs the UI-thread command mechanism
        @fusion_mcp.tool()
        def message_box(message: str) -> str:
            """Display a message box in Fusion 360."""
            try:
                _debug_log("message_tool_debug.txt", f"Message box tool called with: {message}")
                success = show_message_box(message)
                _debug_log("message_tool_debug.txt", f"Direct show result: {success}")
                return "Message displayed successfully (queued if not shown immediately)"
            except Exception as e:
                return f"Error displaying message: {str(e)}"

        # Register all other tools from tools.py
        from .tools import register_tools
        register_tools(fusion_mcp)

        print("Registering prompts...")
        # Define prompts
        @fusion_mcp.prompt()
        def create_sketch_prompt(description: str) -> dict:
            """Create a prompt for creating a sketch based on a description."""
            return {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an expert in Fusion 360 CAD modeling. Your task is to help the user create sketches based on their descriptions.\n\nBe very specific about what planes to use and what sketch entities to create."
                    },
                    {
                        "role": "user",
                        "content": f"I want to create a sketch with these requirements: {description}\n\nPlease provide step-by-step instructions for creating this sketch in Fusion 360."
                    }
                ]
            }

        @fusion_mcp.prompt()
        def parameter_setup_prompt(description: str) -> dict:
            """Create a prompt for setting up parameters based on a description."""
            return {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an expert in Fusion 360 parametric design. Your task is to help the user set up parameters for their design.\n\nSuggest appropriate parameters, their values, units, and purposes based on the user's description."
                    },
                    {
                        "role": "user",
                        "content": f"I want to set up parameters for: {description}\n\nWhat parameters should I create, and what values, units, and comments should they have?"
                    }
                ]
            }

        # Set up file-based communication
        print("Setting up file-based communication...")

        # Create server status file
        server_status_file = comm_dir / "server_status.json"
        with open(server_status_file, "w") as f:
            status_data = {
                "status": "running",
                "started_at": time.ctime(),
                "server_url": "http://127.0.0.1:3000/sse",
                "fusion_version": app.version,
                "addin_root": str(ADDIN_ROOT),
                "available_resources": [
                    "fusion://active-document-info",
                    "fusion://design-structure",
                    "fusion://parameters"
                ],
                "available_tools": [
                    "message_box",
                    "create_new_sketch",
                    "create_parameter",
                    "draw_rectangle",
                    "draw_circle",
                    "draw_line",
                    "finish_sketch",
                    "extrude",
                    "revolve",
                    "fillet",
                    "chamfer",
                    "shell",
                    "get_design_info",
                    "get_body_info",
                    "measure",
                    "draw_arc",
                    "undo",
                    "delete_body",
                    "delete_sketch",
                    "export_stl",
                    "export_step",
                    "fit_view"
                ],
                "available_prompts": [
                    "create_sketch_prompt",
                    "parameter_setup_prompt"
                ]
            }
            json.dump(status_data, f, indent=2)

        # Create ready file in the add-in root
        ready_file = ADDIN_ROOT / "mcp_server_ready.txt"
        try:
            with open(ready_file, "w") as f:
                f.write(f"MCP Server Ready - {time.ctime()}")
            print(f"Created ready file: {ready_file}")
        except Exception as e:
            print(f"Error creating ready file: {str(e)}")

        # Run the FastMCP server
        print("Starting MCP server using FastMCP with uvicorn")

        sse_app = fusion_mcp.sse_app()

        host = "127.0.0.1"
        port = 3000

        config = uvicorn.Config(
            sse_app,
            host=host,
            port=port,
            log_level="info"
        )

        server = uvicorn.Server(config)

        def uvicorn_thread():
            try:
                _debug_log("mcp_server_init.log", f"Starting uvicorn server - Host: {host}, Port: {port}")
                server.run()
            except Exception as e:
                error_msg = f"Error in uvicorn server: {str(e)}"
                print(error_msg)
                error_file = comm_dir / "mcp_server_uvicorn_error.txt"
                with open(error_file, "w") as f:
                    f.write(error_msg + "\n")
                    f.write(traceback.format_exc())

        uv_thread = threading.Thread(target=uvicorn_thread)
        uv_thread.daemon = True
        uv_thread.start()

        print(f"MCP server started at http://{host}:{port}/sse")

        # Monitor for command files
        def file_monitor_thread():
            try:
                print("Starting file monitor thread...")
                _debug_log("file_monitor_status.txt", "File monitor thread started")

                while server_running:
                    try:
                        _ensure_comm_dir()

                        # Check for message box files
                        message_file = comm_dir / "message_box.txt"
                        if message_file.exists():
                            try:
                                with open(message_file, "r") as f:
                                    message = f.read().strip()

                                print(f"Displaying message box: {message}")

                                try:
                                    create_message_box_command(message)
                                except Exception as e:
                                    _debug_log("message_box_processing.txt", f"Command-based display failed: {str(e)}")

                                processed_file = comm_dir / f"processed_message_{int(time.time())}.txt"
                                os.rename(str(message_file), str(processed_file))

                            except Exception as e:
                                print(f"Error processing message file: {str(e)}")

                        # Check for command files
                        for file in os.listdir(str(comm_dir)):
                            if file.startswith("command_") and file.endswith(".json"):
                                command_file = comm_dir / file
                                try:
                                    command_id = file.split("_")[1].split(".")[0]

                                    processed_file = comm_dir / f"processed_command_{command_id}.json"
                                    response_file = comm_dir / f"response_{command_id}.json"

                                    if processed_file.exists() or response_file.exists():
                                        continue

                                    print(f"Processing command file: {command_file}")

                                    with open(command_file, "r") as f:
                                        command_data = json.load(f)

                                    command = command_data.get("command")
                                    params = command_data.get("params", {})

                                    print(f"Processing command {command_id}: {command} with params {params}")

                                    result = _handle_command(command, params)

                                    with open(response_file, "w") as f:
                                        json.dump({"result": result}, f, indent=2)

                                    os.rename(str(command_file), str(processed_file))

                                except json.JSONDecodeError as e:
                                    print(f"Error parsing JSON in {command_file}: {str(e)}")
                                    with open(str(comm_dir / f"response_{command_id}.json"), "w") as f:
                                        json.dump({"error": f"Invalid JSON format: {str(e)}"}, f, indent=2)
                                except Exception as e:
                                    print(f"Error processing command file {command_file}: {str(e)}")
                                    traceback.print_exc()
                                    try:
                                        with open(str(comm_dir / f"response_{command_id}.json"), "w") as f:
                                            json.dump({"error": str(e)}, f, indent=2)
                                    except Exception:
                                        pass
                    except Exception as e:
                        print(f"Error in file monitor loop: {str(e)}")

                    time.sleep(0.5)
            except Exception as e:
                print(f"Error in file monitor thread: {str(e)}")
                error_file = comm_dir / "error.txt"
                with open(error_file, "w") as f:
                    f.write(f"File Monitor Error: {str(e)}\n\n{traceback.format_exc()}")

        file_monitor = threading.Thread(target=file_monitor_thread)
        file_monitor.daemon = True
        file_monitor.start()

        # Keep thread running
        while server_running:
            time.sleep(1)

        # Shutdown the server
        print("Shutting down server...")
        server.should_exit = True

        return True

    except Exception as e:
        print(f"Error in MCP server: {str(e)}")
        try:
            error_file = _ensure_comm_dir() / "mcp_server_error.txt"
            with open(error_file, "w") as f:
                f.write(f"MCP Server Error: {str(e)}\n\n{traceback.format_exc()}")
        except Exception:
            pass
        return False


def _handle_command(command, params):
    """Handle a file-based command and return the result."""
    if command == "list_resources":
        return [
            "fusion://active-document-info",
            "fusion://design-structure",
            "fusion://parameters"
        ]
    elif command == "list_tools":
        return [
            {"name": "message_box", "description": "Display a message box in Fusion 360"},
            {"name": "create_new_sketch", "description": "Create a new sketch on the specified plane"},
            {"name": "create_parameter", "description": "Create a new parameter in the active design"}
        ]
    elif command == "list_prompts":
        return [
            {"name": "create_sketch_prompt", "description": "Create a prompt for creating a sketch based on a description"},
            {"name": "parameter_setup_prompt", "description": "Create a prompt for setting up parameters based on a description"}
        ]
    elif command == "message_box":
        message = params.get("message", "")
        try:
            create_message_box_command(message)
        except Exception as e:
            _debug_log("command_message_debug.txt", f"Command-based display failed: {str(e)}")
        return "Message processed successfully"
    elif command == "create_new_sketch":
        from mcp.server.fastmcp import FastMCP
        # Call the tool function directly - it's defined in run_mcp_server scope
        # For file-based commands, replicate the logic here
        return _create_sketch_direct(params.get("plane_name", "XY"))
    elif command == "create_parameter":
        return _create_parameter_direct(
            params.get("name", f"Param_{int(time.time()) % 10000}"),
            params.get("expression", "10"),
            params.get("unit", "mm"),
            params.get("comment", "")
        )
    elif command == "read_resource":
        uri = params.get("uri", "")
        return _read_resource_direct(uri)
    elif command == "get_prompt":
        prompt_name = params.get("name", "")
        prompt_args = params.get("args", {})
        return _get_prompt_direct(prompt_name, prompt_args)
    else:
        return f"Unknown command: {command}"


def _create_sketch_direct(plane_name):
    """Create a sketch directly (for file-based commands)."""
    try:
        doc = app.activeDocument
        if not doc:
            return "No active document"
        design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
        if not design:
            return "No design in document"
        root_comp = design.rootComponent
        sketch_plane = None
        if plane_name.upper() == "XY":
            sketch_plane = root_comp.xYConstructionPlane
        elif plane_name.upper() == "YZ":
            sketch_plane = root_comp.yZConstructionPlane
        elif plane_name.upper() == "XZ":
            sketch_plane = root_comp.xZConstructionPlane
        else:
            for i in range(root_comp.constructionPlanes.count):
                plane = root_comp.constructionPlanes.item(i)
                if plane.name == plane_name:
                    sketch_plane = plane
                    break
        if not sketch_plane:
            return f"Could not find plane: {plane_name}"
        sketch = root_comp.sketches.add(sketch_plane)
        sketch.name = f"Sketch_MCP_{int(time.time()) % 10000}"
        return f"Sketch created successfully: {sketch.name}"
    except Exception as e:
        return f"Error creating sketch: {str(e)}"


def _create_parameter_direct(name, expression, unit, comment=""):
    """Create a parameter directly (for file-based commands)."""
    try:
        doc = app.activeDocument
        if not doc:
            return "No active document"
        design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
        if not design:
            return "No design in document"
        try:
            param = design.userParameters.add(name, adsk.core.ValueInput.createByString(expression), unit, comment)
            return f"Parameter created: {param.name} = {param.expression}"
        except Exception:
            existing = design.userParameters.itemByName(name)
            if existing:
                existing.expression = expression
                existing.unit = unit
                if comment:
                    existing.comment = comment
                return f"Parameter updated: {existing.name} = {existing.expression}"
            raise
    except Exception as e:
        return f"Error creating parameter: {str(e)}"


def _read_resource_direct(uri):
    """Read a resource directly (for file-based commands)."""
    try:
        doc = app.activeDocument
        if uri == "fusion://active-document-info":
            if not doc:
                return {"error": "No active document"}
            return {
                "name": doc.name,
                "path": doc.dataFile.name if doc.dataFile else "Unsaved",
                "type": "FusionDesignDocumentType" if doc.products.itemByProductType('DesignProductType') else "Unknown"
            }
        elif uri == "fusion://design-structure":
            if not doc:
                return {"error": "No active document"}
            design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
            if not design:
                return {"error": "No design in document"}
            root_comp = design.rootComponent
            return {
                "design_name": design.name,
                "root_component": {
                    "name": root_comp.name,
                    "bodies_count": root_comp.bodies.count,
                    "sketches_count": root_comp.sketches.count,
                    "occurrences_count": root_comp.occurrences.count
                }
            }
        elif uri == "fusion://parameters":
            if not doc:
                return {"error": "No active document"}
            design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
            if not design:
                return {"error": "No design in document"}
            params = []
            for param in design.allParameters:
                params.append({
                    "name": param.name,
                    "value": param.value,
                    "expression": param.expression,
                    "unit": param.unit,
                    "comment": param.comment
                })
            return {"parameters": params}
        else:
            return {"error": f"Unknown resource URI: {uri}"}
    except Exception as e:
        return {"error": str(e)}


def _get_prompt_direct(prompt_name, prompt_args):
    """Get a prompt directly (for file-based commands)."""
    if prompt_name == "create_sketch_prompt":
        description = prompt_args.get("description", "Default sketch")
        return {
            "messages": [
                {"role": "system", "content": "You are an expert in Fusion 360 CAD modeling. Your task is to help the user create sketches based on their descriptions.\n\nBe very specific about what planes to use and what sketch entities to create."},
                {"role": "user", "content": f"I want to create a sketch with these requirements: {description}\n\nPlease provide step-by-step instructions for creating this sketch in Fusion 360."}
            ]
        }
    elif prompt_name == "parameter_setup_prompt":
        description = prompt_args.get("description", "Default parameters")
        return {
            "messages": [
                {"role": "system", "content": "You are an expert in Fusion 360 parametric design. Your task is to help the user set up parameters for their design.\n\nSuggest appropriate parameters, their values, units, and purposes based on the user's description."},
                {"role": "user", "content": f"I want to set up parameters for: {description}\n\nWhat parameters should I create, and what values, units, and comments should they have?"}
            ]
        }
    else:
        return {"error": f"Unknown prompt: {prompt_name}"}


# Function to start the server
def start_server():
    global server_thread
    global server_running

    print("Starting MCP server...")
    comm_dir = _ensure_comm_dir()

    _debug_log("mcp_server_log.txt", "MCP Server starting")

    # Check if MCP is installed
    if not check_mcp_installed():
        print("Required packages not installed. Cannot start server.")
        ui.messageBox("Required packages are not installed. Please install them with:\npip install \"mcp[cli]\" uvicorn")
        return False

    # Check if server is already running
    if server_running and server_thread and server_thread.is_alive():
        print("MCP server is already running")
        return True

    # Reset server state
    server_running = True

    # Start server in a separate thread
    def server_thread_func():
        try:
            success = run_mcp_server()
            if not success:
                print("Failed to start MCP server")
                global server_running
                server_running = False
                ui.messageBox("Failed to start MCP server. See error log for details.")
        except Exception as e:
            print(f"Error in server thread: {str(e)}")
            server_running = False
            error_file = comm_dir / "mcp_server_error.txt"
            with open(error_file, "w") as f:
                f.write(f"MCP Server Thread Error: {str(e)}\n\n{traceback.format_exc()}")

    server_thread = threading.Thread(target=server_thread_func)
    server_thread.daemon = True
    server_thread.start()

    print("MCP server thread started")

    # Wait a moment for the server to initialize
    time.sleep(1)

    # Check if the thread is still alive
    if not server_thread.is_alive():
        print("MCP server thread stopped unexpectedly")
        server_running = False
        return False

    print("MCP server started successfully")
    return True


# Function to stop the server
def stop_server():
    global server_running

    if not server_running:
        print("MCP server is not running")
        return

    server_running = False

    if server_thread and server_thread.is_alive():
        server_thread.join(timeout=2.0)

    print("MCP server stopped")


# Command event handlers
class MCPServerCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs

            inputs.addTextBoxCommandInput('infoInput', '',
                'Click OK to start the MCP Server.\n\n' +
                'This will enable communication between Fusion 360 and MCP clients.\n\n' +
                'Current server status: ' + ('Running' if server_running else 'Not Running'),
                4, True)

            onExecute = MCPServerCommandExecuteHandler()
            cmd.execute.add(onExecute)
            handlers.append(onExecute)

            onDestroy = MCPServerCommandDestroyHandler()
            cmd.destroy.add(onDestroy)
            handlers.append(onDestroy)
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class MCPServerCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            success = start_server()

            if success:
                ui.messageBox(
                    "MCP Server started successfully!\n\n"
                    "Server is running at http://127.0.0.1:3000/sse\n\n"
                    "Ready for client connections."
                )
            else:
                error_message = "Unknown error. See error log for details."
                error_file = _ensure_comm_dir() / "mcp_server_error.txt"
                if error_file.exists():
                    try:
                        with open(error_file, "r") as f:
                            error_message = f.read()
                    except Exception:
                        pass
                ui.messageBox(f"Failed to start MCP Server. Error: {error_message}")
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class MCPServerCommandDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        pass


# Function to stop server on add-in stop
def stop_server_on_stop(context):
    try:
        global server_running

        if server_running:
            print("Stopping MCP server...")
            server_running = False

            _debug_log("mcp_server_shutdown_log.txt", "MCP Server stopped")

            if server_thread and server_thread.is_alive():
                server_thread.join(timeout=2.0)

            print("MCP server stopped")
    except Exception:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


# Function to create the UI elements
def create_ui():
    try:
        command_definitions = ui.commandDefinitions

        mcp_server_cmd_def = command_definitions.itemById('MCPServerCommand')
        if not mcp_server_cmd_def:
            mcp_server_cmd_def = command_definitions.addButtonDefinition(
                'MCPServerCommand', 'MCP Server', 'Start the MCP Server for Fusion 360'
            )

        on_command_created = MCPServerCommandCreatedHandler()
        mcp_server_cmd_def.commandCreated.add(on_command_created)
        handlers.append(on_command_created)

        add_ins_panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        control = add_ins_panel.controls.itemById('MCPServerCommand')
        if not control:
            add_ins_panel.controls.addCommand(mcp_server_cmd_def)

        print("MCP Server command added to UI")
    except Exception:
        if ui:
            ui.messageBox('Failed to create UI:\n{}'.format(traceback.format_exc()))


# Define the required start() and stop() functions for the add-in system
def start():
    """Called when the add-in is started."""
    try:
        create_ui()
    except Exception:
        if ui:
            ui.messageBox('Failed to initialize add-in:\n{}'.format(traceback.format_exc()))


def stop():
    """Called when the add-in is stopped."""
    try:
        stop_server_on_stop(None)

        command_definitions = ui.commandDefinitions
        mcp_server_cmd_def = command_definitions.itemById('MCPServerCommand')
        if mcp_server_cmd_def:
            mcp_server_cmd_def.deleteMe()

        add_ins_panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        control = add_ins_panel.controls.itemById('MCPServerCommand')
        if control:
            control.deleteMe()

        print("MCP Server add-in stopped")
    except Exception:
        if ui:
            ui.messageBox('Failed to clean up add-in:\n{}'.format(traceback.format_exc()))


# Function to create a message box command
def create_message_box_command(message):
    try:
        _debug_log("message_command_debug.txt", f"Creating message box command for: {message}")

        command_id = f"MCPMessageBox_{int(time.time() * 1000)}"

        cmdDefs = ui.commandDefinitions
        cmdDef = cmdDefs.itemById(command_id)
        if cmdDef:
            cmdDef.deleteMe()

        cmdDef = cmdDefs.addButtonDefinition(
            command_id,
            "MCP Message Box",
            f"Display message: {message}",
            ""
        )

        onCommandCreated = MessageBoxCommandCreatedHandler(message)
        cmdDef.commandCreated.add(onCommandCreated)
        message_command_handlers.append(onCommandCreated)

        cmdDef.execute()

        _debug_log("message_command_debug.txt", f"Command execution triggered for: {message}")

        return True
    except Exception as e:
        _debug_log("message_command_debug.txt", f"Error creating message box command: {str(e)}")
        return False


# Simple function to directly try showing a message box
def show_message_box(message):
    """Display a message box in Fusion 360."""
    try:
        _debug_log("message_debug.txt", f"Trying to show message: {message}")
        success = create_message_box_command(message)
        _debug_log("message_debug.txt", f"Command creation result: {success}")
        return success
    except Exception as e:
        _debug_log("message_debug.txt", f"Error showing message box: {str(e)}")
        return False


# Add a Command Handler for showing message boxes
class MessageBoxCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def notify(self, args):
        try:
            _debug_log("message_command_debug.txt", f"MessageBoxCommand executing for: {self.message}")
            ui.messageBox(self.message, "Fusion MCP Message")
            _debug_log("message_command_debug.txt", "Message box displayed successfully")
        except Exception as e:
            _debug_log("message_command_debug.txt", f"Error in command handler: {str(e)}")


class MessageBoxCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def notify(self, args):
        try:
            _debug_log("message_command_debug.txt", f"MessageBoxCommand created for: {self.message}")

            cmd = args.command

            onExecute = MessageBoxCommandExecuteHandler(self.message)
            cmd.execute.add(onExecute)
            message_command_handlers.append(onExecute)

            cmd.isEnabled = True
            cmd.isVisible = False

            _debug_log("message_command_debug.txt", "Command handlers set up")
        except Exception as e:
            _debug_log("message_command_debug.txt", f"Error in command created handler: {str(e)}")
