# Meeting Intelligence — Frontend

This is the Next.js frontend for the Meeting Intelligence platform. It provides a dashboard for reviewing and approving AI-extracted meeting notes.

## Connection to Backend
The frontend communicates with a FastAPI backend. 
- Ensure the backend is running (typically at `http://localhost:8000`).
- Configure `NEXT_PUBLIC_API_URL` in your `.env` if the backend is on a different port.

## Authentication
We use **NextAuth.js (v5)** with **Microsoft Entra ID** and **Resend** (Magic Links).
- **Microsoft Login:** Required for organizational access.
- **Magic Link:** Fallback for registered users.

### Environment Setup
Create a `frontend/.env.local` or update root `.env`:
```env
AUTH_SECRET=          # Generate with `npx auth secret`
AUTH_MICROSOFT_ENTRA_ID_ID=
AUTH_MICROSOFT_ENTRA_ID_SECRET=
AUTH_MICROSOFT_ENTRA_ID_TENANT_ID=
DATABASE_URL=         # NextAuth uses the same DB for session storage
```

## Getting Started
1. `npm install`
2. `npm run dev`
3. Open [http://localhost:3000](http://localhost:3000)
