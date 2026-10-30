from tasks import generate_cases


def test_every_answer_evidence_survives_padding():
    for c in generate_cases('core',42,[256,4096]):
        if 'answer' in c['expected'] and c['family'] not in ('missing-evidence','log-root-cause'):
            assert c['expected']['answer'] in c['messages'][-1]['content'],c['id']


def test_context_list_does_not_change_case_truth():
    one=generate_cases('core',42,[4096])
    two=[c for c in generate_cases('core',42,[256,4096]) if c['context_size']==4096]
    assert {c['id']:c['expected'] for c in one}=={c['id']:c['expected'] for c in two}


def test_evidence_is_really_at_declared_position():
    cases=generate_cases('core',42,[4096],['recall'])
    found=set()
    for c in cases:
        text=c['messages'][-1]['content']
        answer=c['expected']['answer']
        at=text.index(answer)/len(text)
        position=c['variant']%3
        if position==0:assert at<.2
        elif position==1:assert .35<at<.65
        else:assert at>.8
        found.add(position)
    assert found=={0,1,2}
