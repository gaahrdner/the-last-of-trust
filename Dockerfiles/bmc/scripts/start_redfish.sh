#!/bin/bash
set -e

LOGS_DIR="/logs"

# Wait for BMC to boot up
echo "Waiting for BMC to initialize..." | tee -a $LOGS_DIR/redfish_setup.log
sleep 30

# Start a simple HTTP server to simulate Redfish if the real one isn't available
# In a real OpenBMC image, this would be unnecessary
if ! nc -z localhost 443 2>/dev/null; then
    echo "Redfish not detected on BMC, starting simulation service" | tee -a $LOGS_DIR/redfish_setup.log
    mkdir -p /var/lib/openbmc/redfish-mockup
    
    # Create basic Redfish structure
    cat > /var/lib/openbmc/redfish-mockup/index.html <<EOF
<!DOCTYPE html>
<html>
<head>
    <title>Simulated Redfish Service</title>
</head>
<body>
    <h1>Simulated Redfish Service</h1>
    <p>This is a placeholder for the OpenBMC Redfish service.</p>
    <p>In a real OpenBMC deployment, this would provide full Redfish API access.</p>
</body>
</html>
EOF
    
    # Start a simple HTTP server on port 8080
    cd /var/lib/openbmc/redfish-mockup
    python3 -m http.server 8080 | tee -a $LOGS_DIR/redfish_server.log &
    
    echo "Simulated Redfish service started on port 8080" | tee -a $LOGS_DIR/redfish_setup.log
else
    echo "Redfish service detected on BMC" | tee -a $LOGS_DIR/redfish_setup.log
fi

# Set up IPMI simulation if needed
if ! nc -z localhost 623 2>/dev/null; then
    echo "IPMI service not detected, setting up simulation" | tee -a $LOGS_DIR/redfish_setup.log
    
    # Start a simple IPMI simulator
    # This is just a placeholder - a real IPMI simulator would be more complex
    socat TCP-LISTEN:623,fork,reuseaddr EXEC:"echo 'IPMI Simulator'" | tee -a $LOGS_DIR/ipmi_simulator.log &
    
    echo "IPMI simulator started on port 623" | tee -a $LOGS_DIR/redfish_setup.log
else
    echo "IPMI service detected on BMC" | tee -a $LOGS_DIR/redfish_setup.log
fi

# Keep this script running to maintain the services
echo "Redfish and IPMI services initialized" | tee -a $LOGS_DIR/redfish_setup.log
tail -f /dev/null