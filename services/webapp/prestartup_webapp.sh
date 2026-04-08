#!/bin/bash
set -e

# Set proper permissions to the log dir
chown jobfit:jobfit /var/log/webapp

# Create and set proper permissions to the data/resources and shared dir
mkdir -p /data/resources
chown jobfit:jobfit /data
chown jobfit:jobfit /data/resources
chown jobfit:jobfit /shared

