DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role_new') THEN
        DROP TYPE user_role_new;
    END IF;

    CREATE TYPE user_role_new AS ENUM ('admin', 'dev', 'qa');

    ALTER TABLE users
        ALTER COLUMN role TYPE user_role_new
        USING (
            CASE
                WHEN role::text = 'user' THEN 'dev'
                ELSE role::text
            END
        )::user_role_new;

    DROP TYPE user_role;
    ALTER TYPE user_role_new RENAME TO user_role;
END $$;
