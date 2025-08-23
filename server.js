const express = require('express');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'running', uptime: process.uptime() });
});

app.post('/webhook-test', (req, res) => {
  console.log('Webhook received:', req.body);
  res.json({ received: true, payload: req.body });
});

const PORT = 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
