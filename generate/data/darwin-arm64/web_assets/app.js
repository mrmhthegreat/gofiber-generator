document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('genForm');
    const logContainer = document.getElementById('logContainer');
    const clearBtn = document.getElementById('clearLogs');
    const generateBtn = document.getElementById('generateBtn');

    let eventSource = null;

    function addLog(message, type = 'info') {
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        const time = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
        entry.textContent = `[${time}] ${message}`;
        logContainer.appendChild(entry);
        logContainer.scrollTop = logContainer.scrollHeight;
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (eventSource) {
            eventSource.close();
        }

        const selectedSteps = [];
        const skippedSteps = [];
        
        document.querySelectorAll('#togglesGrid input[type="checkbox"]').forEach(chk => {
            const step = chk.getAttribute('data-step');
            if (chk.checked) {
                selectedSteps.push(step);
            } else {
                skippedSteps.push(step);
            }
        });

        const formData = {
            config_path: document.getElementById('configPath').value,
            output_path: document.getElementById('outputPath').value,
            selected_steps: selectedSteps,
            skipped_steps: skippedSteps
        };

        addLog('Starting generation process...', 'system');
        generateBtn.disabled = true;
        generateBtn.textContent = 'GENERATING...';

        try {
            // Establish SSE connection for logs
            eventSource = new EventSource('/logs');
            eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                addLog(data.message, data.type || 'info');
                
                if (data.status === 'completed' || data.status === 'failed') {
                    eventSource.close();
                    generateBtn.disabled = false;
                    generateBtn.textContent = 'GENERATE CODE';
                }
            };
            eventSource.onerror = () => {
                addLog('Log stream disconnected.', 'error');
                eventSource.close();
                generateBtn.disabled = false;
                generateBtn.textContent = 'GENERATE CODE';
            };

            // Trigger generation
            const response = await fetch('/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            if (!response.ok) {
                const err = await response.json();
                addLog(`Error: ${err.message}`, 'error');
                generateBtn.disabled = false;
                generateBtn.textContent = 'GENERATE CODE';
            }

        } catch (error) {
            addLog(`Connection failed: ${error.message}`, 'error');
            generateBtn.disabled = false;
            generateBtn.textContent = 'GENERATE CODE';
        }
    });

    clearBtn.addEventListener('click', () => {
        logContainer.innerHTML = '';
        addLog('Logs cleared.', 'system');
    });
});
