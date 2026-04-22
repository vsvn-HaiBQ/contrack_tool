DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'system_settings'
    ) THEN
        DELETE FROM system_settings
        WHERE key IN (
            'tracker_story_id',
            'tracker_subtask_id',
            'tracker_qa_id',
            'tracker_bug_id',
            'related_ticket_group_tracker_ids'
        );
    END IF;
END $$;
