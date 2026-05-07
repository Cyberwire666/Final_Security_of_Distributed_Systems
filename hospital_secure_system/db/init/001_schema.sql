CREATE TABLE IF NOT EXISTS roles (
  id SERIAL PRIMARY KEY,
  name VARCHAR(30) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS permissions (
  id SERIAL PRIMARY KEY,
  name VARCHAR(80) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role_id INT REFERENCES roles(id) ON DELETE CASCADE,
  permission_id INT REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'user',
  full_name VARCHAR(150) DEFAULT '',
  oauth_provider VARCHAR(40),
  oauth_subject VARCHAR(255),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id INT REFERENCES users(id) ON DELETE CASCADE,
  role_id INT REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS doctors (
  id SERIAL PRIMARY KEY,
  full_name VARCHAR(150) NOT NULL,
  specialty VARCHAR(120) NOT NULL,
  phone VARCHAR(40) DEFAULT '',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS patients (
  id SERIAL PRIMARY KEY,
  owner_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  full_name VARCHAR(150) NOT NULL,
  age INT CHECK (age >= 0 AND age <= 130),
  gender VARCHAR(20) DEFAULT 'unknown',
  phone VARCHAR(40) DEFAULT '',
  diagnosis TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS appointments (
  id SERIAL PRIMARY KEY,
  owner_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  patient_id INT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  doctor_id INT REFERENCES doctors(id) ON DELETE SET NULL,
  appointment_time TIMESTAMP NOT NULL,
  reason TEXT DEFAULT '',
  status VARCHAR(30) DEFAULT 'scheduled',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS medical_records (
  id SERIAL PRIMARY KEY,
  patient_id INT REFERENCES patients(id) ON DELETE CASCADE,
  owner_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  original_filename TEXT NOT NULL,
  stored_filename TEXT NOT NULL,
  content_type VARCHAR(120) NOT NULL,
  file_size INT NOT NULL,
  sha256_hash CHAR(64) NOT NULL,
  processing_status VARCHAR(30) DEFAULT 'queued',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id SERIAL PRIMARY KEY,
  user_id INT,
  action VARCHAR(120) NOT NULL,
  ip_address VARCHAR(64),
  status VARCHAR(40) NOT NULL,
  details TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS background_jobs (
  id SERIAL PRIMARY KEY,
  record_id INT REFERENCES medical_records(id) ON DELETE CASCADE,
  job_type VARCHAR(60) NOT NULL,
  status VARCHAR(30) DEFAULT 'queued',
  details TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO roles(name) VALUES ('admin'), ('user') ON CONFLICT DO NOTHING;
INSERT INTO permissions(name) VALUES
('users:read'), ('users:update'), ('logs:read'), ('metrics:read'),
('patients:read:all'), ('patients:write'), ('records:read:all'), ('records:write'),
('appointments:read:all'), ('appointments:write'), ('doctors:write')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions(role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p WHERE r.name='admin'
ON CONFLICT DO NOTHING;
INSERT INTO role_permissions(role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.name IN ('patients:write','records:write','appointments:write') WHERE r.name='user'
ON CONFLICT DO NOTHING;

INSERT INTO doctors(full_name, specialty, phone) VALUES
('Dr. Sarah Ahmed', 'Cardiology', '+201000000001'),
('Dr. Omar Hassan', 'Neurology', '+201000000002'),
('Dr. Mona Ali', 'Internal Medicine', '+201000000003')
ON CONFLICT DO NOTHING;
