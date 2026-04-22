DELETE FROM system_settings
WHERE key IN (
    'tracker_story_id',
    'tracker_subtask_id',
    'tracker_qa_id',
    'tracker_bug_id',
    'related_ticket_group_tracker_ids'
);
