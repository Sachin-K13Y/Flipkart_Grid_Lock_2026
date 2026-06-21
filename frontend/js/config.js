// ParkIQ — API configuration
// In production this points to the Render backend.
// Change PARKIQ_API_URL to your Render service URL after deployment.
var API_BASE = (function () {
    // If running locally, use localhost
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
        return 'http://localhost:8000';
    }
    // Production — Render backend URL
    // REPLACE THIS with your actual Render URL after deployment
    return 'https://flipkart-grid-lock-2026-2.onrender.com';
})();
