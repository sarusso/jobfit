CREATE DATABASE jobfit;
CREATE USER jobfit_master WITH PASSWORD '949fa84a';
ALTER USER jobfit_master CREATEDB;
GRANT ALL PRIVILEGES ON DATABASE jobfit to jobfit_master;
\c jobfit
GRANT CREATE ON SCHEMA PUBLIC TO jobfit_master;
