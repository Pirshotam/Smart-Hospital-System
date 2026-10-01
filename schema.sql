-- Smart Hospital Bed & Emergency Capacity System
-- MySQL 8.0.16+ schema  (safe to re-run: it drops and recreates the tables)

CREATE DATABASE IF NOT EXISTS hospital_capacity
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hospital_capacity;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS capacity_snapshots, capacity_audit_log, request_status_history,
                     reservations, referral_requests, hospital_services, services,
                     capacity, users, hospitals;
SET FOREIGN_KEY_CHECKS = 1;

-- HOSPITALS
CREATE TABLE hospitals (
  hospital_id         INT AUTO_INCREMENT PRIMARY KEY,
  hospital_name       VARCHAR(200) NOT NULL,
  location            VARCHAR(255) NOT NULL,
  city                VARCHAR(100),
  latitude            DOUBLE NOT NULL,
  longitude           DOUBLE NOT NULL,
  contact             VARCHAR(50),
  verification_status ENUM('pending','verified','rejected') NOT NULL DEFAULT 'pending',
  emergency_available TINYINT(1) NOT NULL DEFAULT 1,
  account_status      ENUM('active','inactive','suspended') NOT NULL DEFAULT 'active',
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- USERS (login + roles)
CREATE TABLE users (
  user_id       INT AUTO_INCREMENT PRIMARY KEY,
  full_name     VARCHAR(150) NOT NULL,
  email         VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role          ENUM('patient','coordinator','hospital_staff','admin') NOT NULL,
  hospital_id   INT NULL,                       -- set only for hospital_staff
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id)
) ENGINE=InnoDB;

-- SPECIALIST SERVICES (cardiology, neurology, ...)
CREATE TABLE services (
  service_id   INT AUTO_INCREMENT PRIMARY KEY,
  service_name VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE hospital_services (
  hospital_id  INT NOT NULL,
  service_id   INT NOT NULL,
  is_available TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (hospital_id, service_id),
  FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id) ON DELETE CASCADE,
  FOREIGN KEY (service_id)  REFERENCES services(service_id)  ON DELETE CASCADE
) ENGINE=InnoDB;

-- CAPACITY (one row per hospital per resource type)
-- `available` is computed, so it can never drift out of sync
CREATE TABLE capacity (
  capacity_id    INT AUTO_INCREMENT PRIMARY KEY,
  hospital_id    INT NOT NULL,
  resource_type  ENUM('general_bed','emergency_bed','icu_bed','nicu_bed','ventilator',
                      'operation_theatre','isolation_bed','dialysis','trauma','ambulance') NOT NULL,
  total_capacity INT NOT NULL,
  occupied       INT NOT NULL DEFAULT 0,
  reserved       INT NOT NULL DEFAULT 0,        -- temporary holds
  unavailable    INT NOT NULL DEFAULT 0,        -- maintenance etc.
  available      INT GENERATED ALWAYS AS (total_capacity - occupied - reserved - unavailable) STORED,
  last_updated   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_hospital_resource (hospital_id, resource_type),
  FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id) ON DELETE CASCADE,
  CONSTRAINT chk_non_negative CHECK (total_capacity >= 0 AND occupied >= 0
                                     AND reserved >= 0 AND unavailable >= 0),
  CONSTRAINT chk_not_overbooked CHECK (occupied + reserved + unavailable <= total_capacity)
) ENGINE=InnoDB;

-- REFERRAL / ADMISSION REQUESTS
CREATE TABLE referral_requests (
  request_id        INT AUTO_INCREMENT PRIMARY KEY,
  patient_reference VARCHAR(100) NOT NULL,            -- keep PII minimal
  created_by        INT NOT NULL,
  required_resource ENUM('general_bed','emergency_bed','icu_bed','nicu_bed','ventilator',
                         'operation_theatre','isolation_bed','dialysis','trauma','ambulance') NOT NULL,
  needs_ventilator  TINYINT(1) NOT NULL DEFAULT 0,
  required_service  INT NULL,
  location          VARCHAR(255),
  latitude          DOUBLE,
  longitude         DOUBLE,
  urgency           ENUM('low','medium','high','critical') NOT NULL DEFAULT 'medium',
  case_summary      TEXT,
  selected_hospital INT NULL,
  match_score       DECIMAL(5,2),
  request_status    ENUM('searching','request_sent','hospital_reviewing','accepted',
                         'patient_transferred','admitted','rejected','cancelled',
                         'expired','no_capacity') NOT NULL DEFAULT 'searching',
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  accepted_at       DATETIME NULL,
  responded_at      DATETIME NULL,                    -- for average response time
  FOREIGN KEY (created_by)        REFERENCES users(user_id),
  FOREIGN KEY (required_service)  REFERENCES services(service_id),
  FOREIGN KEY (selected_hospital) REFERENCES hospitals(hospital_id),
  INDEX idx_requests_status (request_status),
  INDEX idx_requests_hospital (selected_hospital)
) ENGINE=InnoDB;

-- TEMPORARY RESERVATIONS (e.g. 15-minute hold)
CREATE TABLE reservations (
  reservation_id INT AUTO_INCREMENT PRIMARY KEY,
  request_id     INT NOT NULL,
  capacity_id    INT NOT NULL,
  units          INT NOT NULL DEFAULT 1,
  state          ENUM('active','confirmed','expired','released') NOT NULL DEFAULT 'active',
  reserved_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at     DATETIME NOT NULL,                   -- reserved_at + 15 minutes
  FOREIGN KEY (request_id)  REFERENCES referral_requests(request_id) ON DELETE CASCADE,
  FOREIGN KEY (capacity_id) REFERENCES capacity(capacity_id),
  CONSTRAINT chk_units CHECK (units > 0),
  INDEX idx_reservations_active (state, expires_at)
) ENGINE=InnoDB;

-- STATUS HISTORY (powers request tracking + analytics)
CREATE TABLE request_status_history (
  history_id INT AUTO_INCREMENT PRIMARY KEY,
  request_id INT NOT NULL,
  status     ENUM('searching','request_sent','hospital_reviewing','accepted',
                  'patient_transferred','admitted','rejected','cancelled',
                  'expired','no_capacity') NOT NULL,
  changed_by INT NULL,
  changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (request_id) REFERENCES referral_requests(request_id) ON DELETE CASCADE,
  FOREIGN KEY (changed_by) REFERENCES users(user_id)
) ENGINE=InnoDB;

-- AUDIT LOG FOR CAPACITY CHANGES
CREATE TABLE capacity_audit_log (
  log_id       INT AUTO_INCREMENT PRIMARY KEY,
  capacity_id  INT NOT NULL,
  changed_by   INT NULL,
  old_total    INT, new_total    INT,
  old_occupied INT, new_occupied INT,
  reason       VARCHAR(100),     -- 'manual_update', 'referral_transfer_confirmed', ...
  flagged      TINYINT(1) NOT NULL DEFAULT 0,         -- admin review of suspicious updates
  changed_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (capacity_id) REFERENCES capacity(capacity_id),
  FOREIGN KEY (changed_by)  REFERENCES users(user_id)
) ENGINE=InnoDB;

-- DAILY SNAPSHOTS (capacity trends, forecasting, heatmap)
CREATE TABLE capacity_snapshots (
  snapshot_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
  hospital_id    INT NOT NULL,
  resource_type  ENUM('general_bed','emergency_bed','icu_bed','nicu_bed','ventilator',
                      'operation_theatre','isolation_bed','dialysis','trauma','ambulance') NOT NULL,
  occupied       INT NOT NULL,
  total_capacity INT NOT NULL,
  captured_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id),
  INDEX idx_snapshots_hospital_time (hospital_id, captured_at)
) ENGINE=InnoDB;

-- EXAMPLE: safe reservation (one transaction)
-- START TRANSACTION;
--   SELECT available FROM capacity WHERE capacity_id = 1 FOR UPDATE;   -- row lock
--   -- if available >= 1:
--   UPDATE capacity SET reserved = reserved + 1, last_updated = NOW() WHERE capacity_id = 1;
--   INSERT INTO reservations (request_id, capacity_id, expires_at)
--     VALUES (1, 1, DATE_ADD(NOW(), INTERVAL 15 MINUTE));
-- COMMIT;
