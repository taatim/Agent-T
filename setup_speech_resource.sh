#!/bin/bash
set -e

# Configuration
RG_NAME="voicecallingrg"
LOCATION="eastus2" # Matching the existing ACS resource location usually best
SPEECH_NAME="agent-t-speech-$RANDOM" # Random suffix to avoid conflicts
ACS_NAME="taatics" # Derived from logs: providers/microsoft.communication/communicationservices/taatics

echo "🚀 Starting Azure Speech Resource Provisioning..."

# Start
AZ_CMD="./.venv/bin/az"

# 1. Create Cognitive Services Account (Speech)
echo "📦 Creating Speech Resource: $SPEECH_NAME in $RG_NAME..."
$AZ_CMD cognitiveservices account create \
    --name "$SPEECH_NAME" \
    --resource-group "$RG_NAME" \
    --kind "SpeechServices" \
    --sku "S0" \
    --location "$LOCATION" \
    --yes

# 2. Get Endpoint
echo "🔍 Fetching Speech Endpoint..."
SPEECH_ENDPOINT=$($AZ_CMD cognitiveservices account show \
    --name "$SPEECH_NAME" \
    --resource-group "$RG_NAME" \
    --query "properties.endpoint" \
    -o tsv)

echo "✅ Speech Endpoint: $SPEECH_ENDPOINT"

# 3. Get ACS Principal ID (Identity)
echo "🆔 Fetching ACS Principal ID..."
ACS_ID=$($AZ_CMD communication show \
    --name "$ACS_NAME" \
    --resource-group "$RG_NAME" \
    --query "identity.principalId" \
    -o tsv)

if [ -z "$ACS_ID" ]; then
    echo "⚠️  ACS ($ACS_NAME) does not have a System Assigned Identity. Creating one..."
    ACS_ID=$($AZ_CMD communication identity assign \
        --name "$ACS_NAME" \
        --resource-group "$RG_NAME" \
        --system-assigned \
        --query "principalId" \
        -o tsv)
fi
echo "✅ ACS Principal ID: $ACS_ID"

# 4. Get Speech Resource ID
SPEECH_ID=$($AZ_CMD cognitiveservices account show \
    --name "$SPEECH_NAME" \
    --resource-group "$RG_NAME" \
    --query "id" \
    -o tsv)

# 5. Assign Role (Cognitive Services User)
# This allows ACS to talk to Speech
echo "🔑 Assigning 'Cognitive Services User' role to ACS..."
$AZ_CMD role assignment create \
    --assignee "$ACS_ID" \
    --role "Cognitive Services User" \
    --scope "$SPEECH_ID"

echo "✅ Role Assigned."

# 6. Update .env
echo "📝 Updating .env file..."
# Use python to safely update the .env file without destroying other keys
python3 -c "
import os
lines = []
with open('.env', 'r') as f:
    lines = f.readlines()

with open('.env', 'w') as f:
    found = False
    for line in lines:
        if line.startswith('AZURE_OPENAI_SERVICE_ENDPOINT='):
            f.write(f'AZURE_OPENAI_SERVICE_ENDPOINT=\"$SPEECH_ENDPOINT\"\n')
            found = True
        else:
            f.write(line)
    if not found:
        f.write(f'AZURE_OPENAI_SERVICE_ENDPOINT=\"$SPEECH_ENDPOINT\"\n')
"

echo "🎉 Done! New Endpoint set to: $SPEECH_ENDPOINT"
echo "👉 Please restart your agent server."
