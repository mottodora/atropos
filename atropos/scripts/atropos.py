#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Main Atropos command-line interface.
"""
import sys
from atropos import check_importability
from atropos.commands import execute_cli

# Print a helpful error message if the extension modules cannot be imported.
check_importability()

def main(args=sys.argv[1:]):
    """Main method.
    
    Args:
        args: Command-line arguments.
    """
    sys.exit(execute_cli(args))

if __name__ == '__main__':
    main()
