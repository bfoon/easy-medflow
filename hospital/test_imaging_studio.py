"""Imaging studio and Dr. Flow area questions: the enhancement recipe, studio saves, anatomy labels, area questions
(two pictures, positions mapped back to the whole image, privacy kept in the close-up) and deep dives."""
import io
import json
from unittest import mock

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from . import imaging_ai, imaging_studio as S, imaging_tools as T, medical_ai
from .models import ImagingAIRun, ImagingImage
from .test_evidence import Base
from . import test_imaging_ai as tia        # module import: its test class is not collected a second time here

AI_ON = tia.AI_ON
ANTHROPIC = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='anthropic', ANTHROPIC_API_KEY='k', CLINICAL_AI_IMAGING_MAX_TOKENS=4000)


class Fixture(Base):
    """The same patient, study and image as test_imaging_ai, without re-running its tests."""
    setUp = tia.ImagingAITests.setUp
    tearDown = tia.ImagingAITests.tearDown
    post = tia.ImagingAITests.post


def png(arr):
    b = io.BytesIO()
    Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8)).save(b, 'PNG')
    b.seek(0)
    return b


def scene(h=240, w=320, noise=0.0, base=0.5, amp=0.3, seed=1):
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(seed)
    return np.clip(base + amp * np.sin(xx / 9) * np.cos(yy / 13) + rng.normal(0, noise, (h, w)), 0, 1)


class StudioEngineTests(Fixture):
    """The maths and the recipe (no database needed, but kept with the imaging fixtures for one test run)."""

    def test_box_filter_matches_a_direct_mean(self):
        a = np.random.default_rng(3).random((30, 40)).astype(np.float32)
        ref = np.array([[a[max(0, y - 4):y + 5, max(0, x - 4):x + 5].mean() for x in range(40)] for y in range(30)])
        self.assertLess(np.abs(S._box(a, 4) - ref).max(), 1e-5)

    def test_smoothing_removes_grain_but_keeps_an_edge(self):
        g = np.zeros((120, 120), np.float32); g[:, 60:] = 1
        noisy = np.clip(g + np.random.default_rng(0).normal(0, .08, g.shape), 0, 1).astype(np.float32)
        out = S.guided_smooth(noisy, .7)
        self.assertLess(out[:, 5:50].std(), noisy[:, 5:50].std() * .6)            # grain reduced
        self.assertGreater(out[:, 64:].mean() - out[:, :56].mean(), .85)          # edge kept

    def test_recipe_follows_the_picture_and_the_study(self):
        dark_noisy = S.measure(Image.open(png(scene(noise=.08, base=.2, amp=.12))))
        r = S.suggest(dark_noisy, 'xray', 'Left knee')
        self.assertGreaterEqual(r['recipe']['smooth'], .35)
        self.assertGreater(r['recipe']['gamma'], 1)
        self.assertTrue(r['recipe']['level'])
        self.assertIn('Dark', r['issues'])
        self.assertTrue(any('bone cortex' in x['text'] for x in r['reasons']))
        us = S.suggest(S.measure(Image.open(png(scene(noise=.05)))), 'ultrasound', 'Abdomen')['recipe']
        self.assertGreaterEqual(us['smooth'], .55)
        self.assertEqual(us['sharpen'], 0)                                        # never sharpen speckle
        glare = scene(); glare[:, :120] = 1                                       # light box beside the film
        self.assertGreater(S.suggest(S.measure(Image.open(png(glare))), 'xray', 'Chest PA')['recipe']['glare'], 0)

    def test_black_background_is_not_called_dark(self):
        g = np.zeros((240, 320)); g[40:200, 80:240] = scene(160, 160, base=.6)    # an X-ray on black
        m = S.measure(Image.open(png(g)))
        self.assertLess(m['median'], .1)
        self.assertGreater(m['body_median'], .4)
        self.assertNotIn('Dark', S.issues(m))

    def test_studio_processing_colour_relief_and_classic_path(self):
        src = png(scene(noise=.03))
        out, applied = T.process(src, {**S.PRESETS['photo'][1]})
        im = Image.open(io.BytesIO(out))
        self.assertEqual((im.mode, im.size), ('RGB', (320, 240)))
        self.assertEqual(applied['colour'], 'anatomy')
        self.assertIn('illustrative', T.describe(applied))
        src.seek(0)
        out2, applied2 = T.process(src, {'level': True, 'enhance': 2})              # no studio keys: unchanged path
        self.assertEqual(Image.open(io.BytesIO(out2)).mode, 'L')
        self.assertNotIn('smooth', applied2)
        src.seek(0)
        _, bad = T.process(src, {'colour': 'not-a-palette', 'smooth': 9, 'detail': -3})
        self.assertNotIn('colour', bad)
        self.assertEqual(bad['smooth'], 1.0)                                       # clamped

    def test_assist_endpoint_and_permissions(self):
        r = self.as_('doctor').get(reverse('imaging_studio_assist', args=[self.img.pk]))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['ok'])
        self.assertIn('enhance', d['recipe'])
        self.assertIn('photo', d['presets'])
        self.assertTrue(1 <= d['score'] <= 100)
        self.assertEqual(self.as_('reception').get(reverse('imaging_studio_assist', args=[self.img.pk])).status_code, 403)
        self.assertFalse(ImagingAIRun.objects.exists())                            # nothing went to the AI

    def test_studio_save_makes_an_illustrative_copy_and_keeps_the_original(self):
        before = self.img.file.read(); self.img.file.close()
        r = self.post('radiology', 'imaging_process', self.img.pk, {**S.PRESETS['photo'][1], 'grayscale': True, 'save': True})
        d = r.json()
        self.assertTrue(d['ok'], d)
        new = ImagingImage.objects.get(pk=d['id'])
        self.assertEqual(new.derived_from, self.img)
        self.assertIn('illustrative', new.caption)
        self.assertEqual(new.processing['colour'], 'anatomy')
        self.img.refresh_from_db()
        self.assertEqual(self.img.file.read(), before)

    def test_page_has_the_studio_and_area_tool(self):
        page = self.as_('doctor').get(reverse('imaging_detail', args=[self.o.pk])).content.decode()
        self.assertIn('data-act="studio"', page)
        self.assertIn('data-tool="area"', page)
        self.assertIn('imaging-studio.js', page)
        page = self.as_('reception').get(reverse('imaging_detail', args=[self.o.pk]))
        if page.status_code == 200:                                                # no Dr. Flow tools without access
            self.assertNotIn('data-tool="area"', page.content.decode())


class AreaQuestionTests(Fixture):
    REGION_ANSWER = {'summary': 'Cortex intact.', 'quality': 'Good.', 'labels': [
        {'name': 'Cortex', 'box_2d': [0, 0, 500, 500], 'concern': 'normal', 'confidence': 'high', 'explanation': 'x'},
        {'name': 'Tip', 'point': [1000, 1000], 'concern': 'watch', 'confidence': 'low', 'explanation': 'y'}],
        'explanation': '## In this area\nCortex [1].', 'limitations': ''}

    def test_region_helpers(self):
        self.assertIsNone(imaging_ai.clean_region([.1, .1, .01, .01]))           # too small
        self.assertIsNone(imaging_ai.clean_region(None))
        self.assertEqual(imaging_ai.clean_region([.2, .2, .4, .3]), [.2, .2, .4, .3])
        cb = imaging_ai.crop_box([.2, .2, .4, .3])
        self.assertAlmostEqual(cb[0], .2 - .4 * imaging_ai.AREA_MARGIN)
        self.assertEqual(imaging_ai.crop_box([0, 0, 1, 1]), [0.0, 0.0, 1.0, 1.0])  # never outside the image
        mapped = imaging_ai.to_whole([{'box': [0, 0, .5, .5], 'point': None}, {'box': None, 'point': [1, 1]}], [0, 0, 1, 1])
        self.assertEqual(mapped[0]['box'], [0, 0, .5, .5])
        self.assertEqual(mapped[1]['point'], [1, 1])

    def test_covered_names_stay_black_in_the_close_up(self):
        im = Image.new('RGB', (400, 400), (255, 255, 255)); b = io.BytesIO(); im.save(b, 'PNG'); b.seek(0)
        (whole, ww, wh), (close, cw, ch) = imaging_ai.prepare_area(b, [[.25, .25, .25, .25]], [.2, .2, .4, .4])
        c = np.asarray(Image.open(io.BytesIO(close)).convert('L'), dtype=float)
        # the covered box starts at 0.25 of the image = (0.25-0.176)/0.448 of the close-up
        y = int(ch * .4); x = int(cw * .4)
        self.assertLess(c[y, x], 40)                                              # black, not the white film
        self.assertGreater(c[-3, -3], 200)
        w = np.asarray(Image.open(io.BytesIO(whole)).convert('RGB'), dtype=int)
        self.assertTrue((w[:, :, 2] < 100).any())                                 # the yellow outline is drawn

    @AI_ON
    def test_area_question_requires_a_real_area(self):
        r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'region', 'confirm_no_identifiers': True})
        self.assertEqual(r.status_code, 400)
        r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'region', 'region': [.1, .1, .005, .005], 'confirm_no_identifiers': True})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ImagingAIRun.objects.exists())

    @AI_ON
    def test_quick_look_sends_two_pictures_and_maps_labels_to_the_whole_image(self):
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'text': json.dumps(self.REGION_ANSWER)}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'region', 'region': [.5, .5, .4, .4], 'question': 'Is Lamin\'s rib broken?',
                                                                     'confirm_no_identifiers': True, 'redactions': [[0, 0, .2, .2]]})
        self.assertEqual(r.status_code, 200, r.content)
        run = ImagingAIRun.objects.get()
        self.assertEqual((run.status, run.kind, run.depth, run.region), ('done', 'region', 'quick', [.5, .5, .4, .4]), run.error)
        self.assertEqual(sent['task'], 'imaging_region')
        self.assertEqual(len(sent['images']), 2)
        self.assertIn('PICTURE 2', sent['instructions'])
        self.assertNotIn('Lamin', sent['instructions'])
        self.assertIn('selected_area', sent['context'])
        self.assertIn('radiologist_draft', sent['context'])                        # a question sees the draft
        cx, cy, cw, ch = imaging_ai.crop_box([.5, .5, .4, .4])
        box = run.labels[0]['box']                                                 # top-left quarter of the close-up
        self.assertAlmostEqual(box[0], cx, places=3); self.assertAlmostEqual(box[2], cw / 2, places=3)
        self.assertAlmostEqual(run.labels[1]['point'][0], cx + cw, places=3)        # bottom-right corner of the close-up
        d = r.json()['run']
        self.assertEqual(d['region'], [.5, .5, .4, .4])
        self.assertEqual(d['depth'], 'quick')

    @ANTHROPIC
    def test_deep_dive_follow_up_gets_more_room_and_the_earlier_answer(self):
        first = ImagingAIRun.objects.create(image=self.img, order=self.o, kind='region', region=[.3, .3, .3, .3], status='done',
                                            summary='Possible lucency.', labels=[{'n': 1, 'name': 'Lucency'}])
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'content': [{'type': 'text', 'text': json.dumps(self.REGION_ANSWER)}], 'stop_reason': 'end_turn'}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'region', 'region': [.35, .35, .1, .1], 'depth': 'deep',
                                                                     'parent': first.pk, 'confirm_no_identifiers': True})
        run = ImagingAIRun.objects.latest('id')
        self.assertEqual(run.status, 'done', run.error)
        self.assertEqual((run.depth, run.parent_id), ('deep', first.pk))
        self.assertEqual(sent['max_tokens'], int(4000 * 1.6))
        parts = sent['messages'][0]['content']
        self.assertEqual([p['type'] for p in parts], ['image', 'image', 'text'])
        text = parts[-1]['text']
        self.assertIn('DEEP DIVE', text)
        self.assertIn('Possible lucency.', text)                                   # the earlier answer is in the context
        self.assertIn('diving_deeper_from', text)
        self.assertEqual(r.json()['run']['parent'], first.pk)

    @AI_ON
    def test_parent_from_another_image_is_ignored(self):
        other = ImagingImage.objects.create(order=self.o, file=SimpleUploadedFile('b.png', png(scene()).getvalue()))
        foreign = ImagingAIRun.objects.create(image=other, order=self.o, kind='region', region=[.1, .1, .3, .3], status='done')
        with mock.patch.object(medical_ai, '_post_json', lambda *a, **k: {'text': json.dumps(self.REGION_ANSWER)}):
            self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'region', 'region': [.2, .2, .3, .3], 'parent': foreign.pk, 'confirm_no_identifiers': True})
        self.assertIsNone(ImagingAIRun.objects.filter(image=self.img).get().parent_id)

    @AI_ON
    def test_anatomy_labels_use_their_own_task(self):
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'text': json.dumps({'summary': 'Anatomy.', 'labels': [{'name': 'Trachea', 'point': [100, 500], 'concern': 'normal'}],
                                        'explanation': '## Anatomy shown\n- Trachea [1]'})}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('nurse', 'imaging_ai_ask', self.img.pk, {'kind': 'anatomy', 'confirm_no_identifiers': True})
        run = ImagingAIRun.objects.get()
        self.assertEqual((run.status, run.kind), ('done', 'anatomy'), run.error)
        self.assertEqual(sent['task'], 'imaging_anatomy')
        self.assertIn('NORMAL ANATOMY', sent['instructions'])
        self.assertEqual(len(sent['images']), 1)
        self.assertEqual(r.json()['run']['labels'][0]['name'], 'Trachea')

    def test_preview_of_an_area_shows_both_pictures(self):
        r = self.post('doctor', 'imaging_ai_preview', self.img.pk, {'kind': 'region', 'region': [.2, .2, .5, .5], 'redactions': [[0, 0, .1, .1]]})
        d = r.json()
        self.assertEqual(len(d['images']), 2)
        self.assertIn('selected_area', d['context'])
        self.assertNotIn('Lamin', d['context'])
        self.assertFalse(ImagingAIRun.objects.exists())


class OutlineTests(Fixture):
    OUTLINE_ANSWER = {'summary': 'Outlined.', 'labels': [
        {'name': 'Heart', 'outline': [[400, 300], [400, 700], [800, 700], [800, 300]], 'concern': 'normal', 'confidence': 'moderate'},
        {'name': 'Bad', 'outline': [[1, 1], [2, 2]], 'concern': 'normal'},                       # too few points: kept without outline
        {'name': 'Flat', 'outline': [[100, 100], [100, 200], [100, 300]], 'concern': 'watch'}],    # no area
        'explanation': '## Outlined\n- Heart [1]'}

    def test_outlines_are_parsed_and_boxed(self):
        ans = imaging_ai.parse_answer(json.dumps(self.OUTLINE_ANSWER))
        heart, bad, flat = ans['labels']
        self.assertEqual(heart['outline'][0], [0.3, 0.4])                                          # [y, x] 0-1000 -> [x, y] 0-1
        self.assertEqual(heart['box'], [0.3, 0.4, 0.4, 0.4])                                      # a box is made around it
        self.assertIsNone(bad['outline']); self.assertIsNone(flat['outline'])
        many = imaging_ai._outline([[500 + 300 * np.sin(t), 500 + 300 * np.cos(t)] for t in np.linspace(0, 6.2, 300)])
        self.assertEqual(len(many), imaging_ai.MAX_OUTLINE_POINTS)

    @AI_ON
    def test_outline_run_names_what_to_outline(self):
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'text': json.dumps(self.OUTLINE_ANSWER)}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'outline', 'question': 'the heart and Lamin\'s lungs', 'confirm_no_identifiers': True})
        run = ImagingAIRun.objects.get()
        self.assertEqual((run.status, run.kind), ('done', 'outline'), run.error)
        self.assertEqual(sent['task'], 'imaging_outline')
        self.assertIn('Outline on this image: the heart and', sent['instructions'])
        self.assertNotIn('Lamin', sent['instructions'])
        self.assertEqual(r.json()['run']['labels'][0]['outline'][2], [0.7, 0.8])
        with mock.patch.object(medical_ai, '_post_json', post):                                   # no names: main organs and abnormalities
            self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'outline', 'confirm_no_identifiers': True})
        self.assertIn(imaging_ai.DEFAULT_OUTLINE, sent['instructions'])

    @AI_ON
    def test_area_question_about_a_drawn_shape(self):
        shape = [[.2, .2], [.6, .25], [.55, .7], [.25, .6]]
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'text': json.dumps({'summary': 'Soft tissue.', 'labels': [{'name': 'Edge', 'outline': [[0, 0], [0, 1000], [1000, 1000], [1000, 0]]}],
                                        'explanation': '## In this area\nx'})}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'region', 'shape': shape, 'confirm_no_identifiers': True})
        self.assertEqual(r.status_code, 200, r.content)
        run = ImagingAIRun.objects.get()
        self.assertEqual(run.status, 'done', run.error)
        self.assertEqual(run.shape, shape)
        self.assertEqual(run.region, [0.2, 0.2, 0.4, 0.5])                                       # the box comes from the shape
        self.assertIn('freehand shape', sent['instructions'])
        self.assertTrue(sent['context']['selected_area']['outlined_with_a_freehand_shape'])
        cx, cy, cw, ch = imaging_ai.crop_box(run.region)
        self.assertAlmostEqual(run.labels[0]['outline'][2][0], cx + cw, places=3)                 # close-up corner -> whole image
        self.assertEqual(imaging_ai.clean_shape([[0, 0], [1, 1]]), [])
        self.assertEqual(len(imaging_ai.clean_shape([[i / 500, .5] for i in range(500)])), 100)

    def test_outline_annotations_are_saved_and_cleaned(self):
        poly = {'type': 'polygon', 'points': [[10, 10], [100, 12], [90, 80]], 'label': 'Heart', 'kind': 'organ', 'source': 'smart', 'color': '#4FC3F7', 'text': 'n'}
        r = self.post('radiology', 'imaging_annotations', self.img.pk, {'annotations': [
            poly, {**poly, 'points': [[1, 1], [2, 2]]}, {**poly, 'kind': 'hack', 'source': 'x', 'color': 'red;}', 'label': 'L' * 99}]})
        self.assertEqual(r.json()['count'], 2)
        self.img.refresh_from_db()
        a, b = self.img.annotations
        self.assertEqual((a['type'], a['kind'], a['source'], a['color']), ('polygon', 'organ', 'smart', '#4FC3F7'))
        self.assertEqual((b['kind'], b['source'], b['color'], len(b['label'])), ('other', 'drawn', '', 60))
        page = self.as_('radiology').get(reverse('imaging_detail', args=[self.o.pk])).content.decode()
        self.assertIn('data-tool="wand"', page)
        self.assertIn('data-find', page)
        self.assertIn('imaging-segment.js', page)
