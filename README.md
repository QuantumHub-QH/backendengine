MCHLERN BINARY ENGINE

Backend API untuk proyek MCHLERN.

Deploy Railway

1. Push semua file ke GitHub.
2. Buka Railway.
3. Pilih Deploy from GitHub Repo.
4. Pilih repository MCHLERN.
5. Tambahkan variable API_TOKEN.
6. Deploy.

API

GET /
GET /health

POST /api/upload/rbxm
POST /api/upload/rbxl

GET /api/jobs/{job_id}
GET /api/jobs/{job_id}/manifest

Authentication

Semua endpoint API selain / dan /health memerlukan:

Authorization: Bearer YOUR_API_TOKEN

Status

Backend upload dan API sudah disiapkan.

Decoder binary RBXM/RBXL masih perlu diintegrasikan. Delta client dan sistem rekonstruksi StudioLite juga merupakan komponen terpisah.

Hasil job sementara disimpan di memory dan hilang ketika service restart.

Jangan mengunggah file yang tidak memiliki izin untuk digunakan.
