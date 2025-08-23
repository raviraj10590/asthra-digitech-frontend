const express = require('express');
const cors = require('cors');
const app = express();
const PORT = 3000;

// Middleware
app.use(cors());
app.use(express.json());

// POST endpoint for webhook
app.post('/webhook', (req, res) => {
    console.log('Webhook received at:', new Date().toISOString());
    console.log('Payload:', req.body);
    
    // Respond with success
    res.json({ 
        status: "ok", 
        message: "Data received",
        receivedAt: new Date().toISOString()
    });
});

// GET health endpoint
app.get('/health', (req, res) => {
    res.json({ status: "running" });
});

// Start server
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
    console.log(`Health check available at http://localhost:${PORT}/health`);
    console.log(`Webhook endpoint available at http://localhost:${PORT}/webhook`);
});
