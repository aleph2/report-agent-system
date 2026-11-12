"""Read-time PDF geometry hints; no OCR, semantic classification or stored state."""
import math

GRID = 200


def unavailable():
    return {'status':'unavailable','graphics_grid':[GRID,GRID],
            'graphics_coverage':None,'image_coverage':None,'vector_coverage':None,'scan_like':None}


def _grid(boxes, bbox):
    x0,y0,x1,y1=bbox
    rows=[0]*GRID
    for a,b,c,d in boxes:
        if not all(math.isfinite(v) for v in (a,b,c,d)):
            raise ValueError('Nonfinite geometry')
        left=max(0,min(GRID,math.floor((a-x0)*GRID/(x1-x0))))
        right=max(0,min(GRID,math.ceil((c-x0)*GRID/(x1-x0))))
        top=max(0,min(GRID,math.floor((b-y0)*GRID/(y1-y0))))
        bottom=max(0,min(GRID,math.ceil((d-y0)*GRID/(y1-y0))))
        if right<=left or bottom<=top:continue
        mask=((1<<(right-left))-1)<<left
        for y in range(top,bottom):rows[y]|=mask
    return rows


def observe(page):
    try:
        visible=page.crop(page.cropbox) if page.cropbox!=page.bbox else page
        bbox=visible.bbox
        if bbox[2]<=bbox[0] or bbox[3]<=bbox[1]:raise ValueError('Empty page')
        box=lambda obj:(obj['x0'],obj['top'],obj['x1'],obj['bottom'])
        images=[box(obj) for obj in visible.images]
        vectors=[box(obj) for obj in visible.rects+visible.curves+visible.lines]
        image_grid,vector_grid=_grid(images,bbox),_grid(vectors,bbox)
        coverage=lambda rows:sum(row.bit_count() for row in rows)/(GRID*GRID)
        native=len(visible.chars)
        scan_like=len(images)==1 and native==0 and all(
            abs(a-b)<=.5 for a,b in zip(images[0],bbox))
        return {'status':'observed','graphics_grid':[GRID,GRID],
            'coordinate_system':'PDF points (x0,top,x1,bottom), visible page crop/rotation',
            'page_bbox':bbox,'native_character_count':native,'image_count':len(images),
            'image_coverage':coverage(image_grid),'vector_coverage':coverage(vector_grid),
            'graphics_coverage':coverage([a|b for a,b in zip(image_grid,vector_grid)]),
            'scan_like':scan_like,'scan_like_rule':'One image covers visible page within 0.5 PDF point, with no native text; not proof of scanned origin.',
            'limitations':['200x200 occupied-cell approximation of clipped image/vector bounding boxes, not painted ink or semantic coverage.','No OCR or OCR-quality estimate.']}
    except Exception:
        return unavailable()
