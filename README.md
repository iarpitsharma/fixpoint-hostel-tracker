# FixPoint - Hostel Grievance Portal

FixPoint is an SLA-driven hostel grievance tracking and resolution web application built with Python Flask, SQLite, and Tailwind CSS. It introduces student upvoting to prevent duplicate tickets and dynamic 24-hour SLA auto-escalation to ensure administrative accountability.

## Features
- **Student Dashboard:** Submit grievance tickets with category, priority, description, and optional photo attachment.
- **Crowdsourced Impact:** Students can upvote active issues to highlight widespread hostel problems without cluttering the feed.
- **SLA Auto-Escalation:** Grievances pending beyond 24 hours automatically shift to an "Escalated" status.
- **Warden Command Center:** Real-time metrics overview (Total, Pending, In Progress, Escalated, Resolved), status updates, and resolution notes.

## Tech Stack
- **Backend:** Python (Flask)
- **Database:** SQLite
- **Frontend:** HTML5, Tailwind CSS (via CDN)
- **Security:** Werkzeug password hashing, session-based role authorization

## Getting Started

1. Clone the repository:
   ```bash
   git clone [https://github.com/YOUR_USERNAME/hostel-grievance-tracker.git](https://github.com/YOUR_USERNAME/hostel-grievance-tracker.git)
   cd hostel-grievance-tracker