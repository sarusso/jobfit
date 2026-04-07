FROM ubuntu:22.04
MAINTAINER Stefano Alberto Russo <stefano.russo@gmail.com>

#----------------------
# Basics
#----------------------

# Set non-interactive
ENV DEBIAN_FRONTEND noninteractive

# Update
RUN apt-get update

# Utilities
RUN apt-get install -y nano telnet unzip wget supervisor openssh-server

# Devel
RUN apt-get install -y build-essential python3-dev git-core

# Java
RUN apt-get install -y openjdk-8-jre

# IP utilities (mandatory for DNS!)
RUN apt-get install net-tools iproute2 iputils-ping -y


#------------------------
# JobFit user
#------------------------

# Add group. We chose GID 65527 to try avoiding conflicts.
RUN groupadd -g 65527 jobfit

# Add user. We chose UID 65527 to try avoiding conflicts.
RUN useradd jobfit -d /jobfit -u 65527 -g 65527 -m -s /bin/bash

# Add jobfit user to sudoers
RUN adduser jobfit sudo

# Keys
RUN mkdir /jobfit/.ssh
COPY keys/authorized_keys /jobfit/.ssh/
COPY keys/id_rsa /jobfit/.ssh/
RUN chmod 0600 /jobfit/.ssh/id_rsa
COPY keys/id_rsa.pub /jobfit/.ssh/
RUN chown -R jobfit:jobfit /jobfit/.ssh

# Install suodo
RUN apt-get install sudo -y

# No pass sudo (for everyone, actually)
COPY sudoers /etc/sudoers

# bash_profile for loading correct env (/env.sh created by entrypoint.sh)
RUN echo "source /env.sh" > /jobfit/.bash_profile


#------------------------
# Data, Logs and opt dirs
#------------------------

# Create dirs
RUN mkdir /data && mkdir /var/log/jobfit 

# Give right permissions
RUN chown -R jobfit:jobfit /data && chown -R jobfit:jobfit /var/log/jobfit


#----------------------
#  Supervisord conf
#----------------------

COPY supervisord.conf /etc/supervisor/


#----------------------
# SSH conf
#----------------------

RUN mkdir /var/run/sshd && chmod 0755 /var/run/sshd
COPY supervisord_sshd.conf /etc/supervisor/conf.d/


#----------------------
# Prestartup scripts
#----------------------

# Create dir for prestartup scripts and copy main script
RUN mkdir /prestartup
COPY prestartup.py /



#----------------------
# Entrypoint
#----------------------

# Copy entrypoint
COPY entrypoint.sh /

# Give right permissions
RUN chmod 755 /entrypoint.sh

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]


