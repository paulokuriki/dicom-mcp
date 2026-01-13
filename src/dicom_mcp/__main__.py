"""
Main entry point for the DICOM MCP Server.
"""
import argparse
import logging
import os

from .server import create_dicom_mcp_server

def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="level=%(levelname)s logger=%(name)s %(message)s",
    )

def main():
    # Simple argument parser
    parser = argparse.ArgumentParser(description="DICOM Model Context Protocol Server")
    parser.add_argument("config_path", help="Path to the DICOM configuration YAML file")
    parser.add_argument(
        "--transport",
        help="MCP transport type ('sse' or 'stdio')",
        default="stdio",
    )

    args = parser.parse_args()
    
    # Create and run the server
    _configure_logging()
    mcp = create_dicom_mcp_server(args.config_path)
    mcp.run(args.transport)
    
if __name__ == "__main__":
    main()
