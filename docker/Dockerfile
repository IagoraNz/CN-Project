FROM ubuntu:22.04

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install essential tools
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    net-tools \
    iproute2 \
    tcpdump \
    tshark \
    iputils-ping \
    curl \
    wget \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    numpy \
    pandas \
    matplotlib \
    seaborn \
    plotly

# Create working directory
WORKDIR /app

# Copy project files
COPY . /app/

# Expose ports for client and server
EXPOSE 9000 9001

# Default command
CMD ["/bin/bash"]
