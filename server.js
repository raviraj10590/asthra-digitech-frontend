const express = require('express');
const cors = require('cors');
const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Request logging middleware
app.use((req, res, next) => {
    console.log(`${new Date().toISOString()} - ${req.method} ${req.path}`);
    next();
});

// POST endpoint for webhook
app.post('/webhook', (req, res) => {
    try {
        console.log('Webhook received at:', new Date().toISOString());
        console.log('Headers:', req.headers);
        console.log('Payload:', JSON.stringify(req.body, null, 2));
        
        // Validate that we have a body
        if (!req.body || Object.keys(req.body).length === 0) {
            console.warn('Empty payload received');
            return res.status(400).json({ 
                status: "error", 
                message: "Empty payload received" 
            });
        }
        
        // Respond with success
        res.json({ 
            status: "success", 
            message: "Data received successfully",
            receivedAt: new Date().toISOString(),
            dataId: req.body.id || 'unknown'
        });
    } catch (error) {
        console.error('Error processing webhook:', error);
        res.status(500).json({ 
            status: "error", 
            message: "Internal server error",
            error: error.message 
        });
    }
});

// GET health endpoint
app.get('/health', (req, res) => {
    res.json({ 
        status: "running",
        timestamp: new Date().toISOString(),
        uptime: process.uptime()
    });
});

// Root endpoint
app.get('/', (req, res) => {
    res.send(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Byras Webhook Receiver</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
                .container { max-width: 800px; margin: 0 auto; }
                .endpoint { background: #f4f4f4; padding: 15px; border-radius: 5px; margin: 10px 0; }
                code { background: #eee; padding: 2px 5px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Byras Webhook Receiver</h1>
                <p>Server is running successfully on port ${PORT}</p>
                
                <div class="endpoint">
                    <h3>Endpoints:</h3>
                    <p><strong>GET</strong> <code>/health</code> - Server health check</p>
                    <p><strong>POST</strong> <code>/webhook</code> - Webhook receiver for Byras.com data</p>
                </div>
                
                <div class="endpoint">
                    <h3>Test the Webhook:</h3>
                    <p>Use the following cURL command to test:</p>
                    <code>
                        curl -X POST http://localhost:${PORT}/webhook \<br>
                        -H "Content-Type: application/json" \<br>
                        -d '{"event": "test", "id": "123", "message": "Test payload"}'
                    </code>
                </div>
            </div>
        </body>
        </html>
    `);
});

// Handle 404 errors
app.use('*', (req, res) => {
    res.status(404).json({ 
        status: "error", 
        message: "Endpoint not found" 
    });
});

// Error handling middleware
app.use((error, req, res, next) => {
    console.error('Unhandled error:', error);
    res.status(500).json({ 
        status: "error", 
        message: "Internal server error" 
    });
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on port ${PORT}`);
    console.log(`Health check: http://localhost:${PORT}/health`);
    console.log(`Webhook endpoint: http://localhost:${PORT}/webhook`);
    console.log(`Server info: http://localhost:${PORT}/`);
});

// Handle graceful shutdown
process.on('SIGINT', () => {
    console.log('\nShutting down gracefully...');
    process.exit(0);
});
