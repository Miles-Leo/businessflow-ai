from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session
from app.db.models import Ticket
from app.services.application_dedup import check_application, DuplicateApplication

PROPOSAL = {'order_id':'BF2026001','issue_type':'shipping_delay'}


def graph_with(status, order_id='BF2026001'):
    graph = Mock()
    graph.checkpointer.list.return_value = [SimpleNamespace(config={'configurable':{'thread_id':'existing'}})]
    graph.get_state.return_value = SimpleNamespace(values={'proposal':{**PROPOSAL,'order_id':order_id,'approval_status':status}})
    return graph


@pytest.mark.parametrize('status',['pending','approved'])
def test_active_review_blocks_another_application(db_engine,status):
    with Session(db_engine) as session, pytest.raises(DuplicateApplication):
        check_application(graph_with(status),session,PROPOSAL)


def test_rejected_review_allows_new_application(db_engine):
    with Session(db_engine) as session:
        check_application(graph_with('rejected'),session,PROPOSAL)


def test_other_order_and_same_review_reentry_are_not_duplicates(db_engine):
    with Session(db_engine) as session:
        check_application(graph_with('pending','BF2026002'),session,PROPOSAL)
        check_application(graph_with('pending'),session,PROPOSAL,own_approval_id='existing')


@pytest.mark.parametrize('status,blocked',[('open',True),('in_progress',True),('closed',False)])
def test_formal_ticket_blocks_even_when_review_checkpoint_is_missing(db_engine,status,blocked):
    now=datetime.now(timezone.utc)
    with Session(db_engine) as session, session.begin():
        session.add(Ticket(ticket_id='TK-existing',approval_id='existing',order_id='BF2026001',issue_type='shipping_delay',description='test',status=status,created_at=now,reviewed_at=now,reviewer_id='reviewer-demo-001',executed_by='reviewer-demo-001',policy_sources=[]))
    graph=graph_with('approved')
    with Session(db_engine) as session:
        if blocked:
            with pytest.raises(DuplicateApplication): check_application(graph,session,PROPOSAL)
        else:
            check_application(graph,session,PROPOSAL)
