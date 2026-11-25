from utility_agents import demo, request_path


def test_every_demo_scene_is_a_request_the_system_can_load():
    for request_id, _title, _point in demo.SCENES:
        assert request_path.request(request_id).id == request_id
