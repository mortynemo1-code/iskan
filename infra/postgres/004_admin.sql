CREATE TABLE IF NOT EXISTS departments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    parent_id uuid REFERENCES departments(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (parent_id IS NULL OR parent_id <> id)
);

ALTER TABLE employees ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS department_id uuid REFERENCES departments(id);
ALTER TABLE employees ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
CREATE UNIQUE INDEX IF NOT EXISTS employees_email_unique_idx
    ON employees(lower(email)) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS employees_department_id_idx ON employees(department_id);

INSERT INTO departments(name)
SELECT DISTINCT trim(department_name)
FROM employees
WHERE department_name IS NOT NULL AND trim(department_name) <> ''
ON CONFLICT(name) DO NOTHING;

UPDATE employees e
SET department_id = d.id
FROM departments d
WHERE e.department_id IS NULL AND d.name = trim(e.department_name);

ALTER TABLE devices ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE categories ADD COLUMN IF NOT EXISTS color text NOT NULL DEFAULT '#78909C';
ALTER TABLE categories ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE categories ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

UPDATE categories SET color = CASE code
    WHEN 'development' THEN '#2E7D32'
    WHEN 'office' THEN '#43A047'
    WHEN 'social' THEN '#EF6C00'
    WHEN 'video' THEN '#F9A825'
    ELSE '#78909C'
END;

ALTER TABLE rules ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
