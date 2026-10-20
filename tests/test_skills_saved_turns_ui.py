from tests.helpers.node import run_node_module


def test_skills_summary_metrics_and_quick_filters_behave():
    result = run_node_module(
        """
        import {
          auditNumber,
          filterSkillsByQuickFilter,
          skillsSummaryMetrics,
        } from './static/js/skillsMetrics.js';

        const skills = [
          { name: 'fast', status: 'published', confidence: 0.95, audit_verdict: 'pass', saved_turns: 3 },
          { name: 'slow', status: 'published', confidence: 0.95, audit_verdict: 'pass', saved_turns: -1, saved_tool_calls: -1, baseline_verdict: 'worse', usefulness: 0.1 },
          { name: 'drafty', status: 'draft', confidence: 0.6 },
          { name: 'dup', status: 'draft', confidence: 0.9, audit_verdict: 'pass', necessity: { necessary: false, redundant_with: ['fast'], reason: 'duplicate' } },
          { name: 'broad-zero', status: 'draft', confidence: 0.9, audit_verdict: 'pass', saved_turns: 0, necessity: { necessary: false, redundant_with: [], reason: 'generic but maybe useful' } },
        ];
        const names = filter => filterSkillsByQuickFilter(skills, filter).map(s => s.name);
        console.log(JSON.stringify({
          nested: auditNumber({ verdict: { saved_turns: '4' } }, 'saved_turns'),
          metrics: skillsSummaryMetrics(skills, 0.85),
          saved: names('saved'),
          approved: names('approved'),
          unaudited: names('unaudited'),
          review: names('review'),
          draft: names('draft'),
        }));
        """
    )

    assert result == {
        "nested": 4,
        "metrics": {
            "total": 5,
            "approved": 2,
            "proven": 1,
            "needsAudit": 1,
            "audited": 4,
            "review": 2,
            "drafts": 3,
            "binned": 0,
            "savedTurns": 3,
        },
        "saved": ["fast"],
        "approved": ["fast", "slow"],
        "unaudited": ["drafty"],
        "review": ["dup", "broad-zero"],
        "draft": ["drafty", "dup", "broad-zero"],
    }


def test_builtin_skills_are_preapproved_and_excluded_from_audit_queues():
    result = run_node_module(
        """
        import {
          filterSkillsByQuickFilter,
          skillsSummaryMetrics,
        } from './static/js/skillsMetrics.js';

        const skills = [
          { name: 'core', source: 'builtin', status: 'published', confidence: 1 },
          { name: 'draft', source: 'user', status: 'draft', confidence: 0.5 },
        ];
        const names = filter => filterSkillsByQuickFilter(skills, filter).map(s => s.name);
        console.log(JSON.stringify({
          metrics: skillsSummaryMetrics(skills, 0.85),
          approved: names('approved'),
          builtin: names('builtin'),
          unaudited: names('unaudited'),
        }));
        """
    )

    assert result == {
        "metrics": {
            "total": 2,
            "approved": 1,
            "proven": 1,
            "needsAudit": 1,
            "audited": 0,
            "review": 0,
            "drafts": 1,
            "binned": 0,
            "savedTurns": 0,
        },
        "approved": [],
        "builtin": ["core"],
        "unaudited": ["draft"],
    }
