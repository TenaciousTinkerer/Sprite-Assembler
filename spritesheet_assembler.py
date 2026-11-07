"""SpriteSheet Assembler — desktop GUI. Requires Pillow: pip install pillow"""
import json
import math
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Declare DPI awareness before Tk initializes any windows or native file dialogs.
# Prefer per-monitor v2, then per-monitor v1, then system-aware for older Windows.
def enable_windows_dpi_awareness():
    if os.name != 'nt':
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        set_context = getattr(user32, 'SetProcessDpiAwarenessContext', None)
        if set_context is not None:
            set_context.argtypes = [wintypes.HANDLE]
            set_context.restype = wintypes.BOOL
            if set_context(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
                return
    except (OSError, AttributeError, ValueError):
        pass
    try:
        import ctypes
        shcore = ctypes.WinDLL('shcore')
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        if shcore.SetProcessDpiAwareness(2) == 0:
            return
    except (OSError, AttributeError, ValueError):
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except (OSError, AttributeError):
        pass

enable_windows_dpi_awareness()
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageOps
from tkinterdnd2 import TkinterDnD, DND_FILES

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title('SpriteSheet Assembler')
        self.geometry('1120x780')
        self.minsize(760, 520)
        self.configure(bg='#171a21')
        self.paths = []
        self.cells = []
        self.selected_source = None
        self.drag_cell = None
        self.drag_source = None
        self.preview_cache = {}
        self.columns = tk.IntVar(value=3)
        self.rows = tk.IntVar(value=3)
        self.cell_size = tk.IntVar(value=512)
        self.fit_mode = tk.StringVar(value='Original pixels (no resize)')
        self.status = tk.StringVar(value='Import PNGs, then click a source and click a cell to place it. Drag cells to rearrange.')
        self._make_ui()
        self.report_callback_exception = self._report_callback_exception
        self.rebuild_grid()
        self.log('Application started. Local-only image processing.')

    def _make_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TFrame', background='#171a21')
        style.configure('TLabel', background='#171a21', foreground='#e7e9ed')
        style.configure('TButton', padding=6)
        style.configure('TEntry', fieldbackground='#252a35', foreground='#ffffff')
        style.configure('TCombobox', fieldbackground='#252a35', foreground='#ffffff')
        style.configure('TSpinbox', fieldbackground='#252a35', foreground='#ffffff')
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill='x')
        for name, cmd in [('Import PNGs', self.import_files), ('Save Project', self.save_project), ('Open Project', self.open_project), ('Export PNG', self.export_png)]:
            ttk.Button(bar, text=name, command=cmd).pack(side='left', padx=(0, 7))
        settings = ttk.Frame(self, padding=(10,0,10,10))
        settings.pack(fill='x')
        for name, var in [('Columns',self.columns), ('Rows',self.rows), ('Cell Size',self.cell_size)]:
            ttk.Label(settings,text=name).pack(side='left',padx=(0,4))
            ttk.Spinbox(settings,from_=1,to=1000,width=6,textvariable=var).pack(side='left',padx=(0,12))
        ttk.Button(settings,text='Apply Grid',command=self.rebuild_grid).pack(side='left',padx=(0,10))
        ttk.Combobox(settings,textvariable=self.fit_mode,values=['Original pixels (no resize)','Contain (no upscaling)','Contain (allow scaling)','Center original (crop overflow)','Stretch to cell'],state='readonly',width=27).pack(side='left')
        self.output_label = ttk.Label(self, text='Output: 384 × 384 px (automatically calculated)', padding=(10,0,10,8))
        self.output_label.pack(anchor='w')
        paned = ttk.Panedwindow(self,orient='horizontal')
        paned.pack(fill='both',expand=True,padx=10,pady=(0,8))
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left,weight=1)
        paned.add(right,weight=3)
        ttk.Label(left,text='SOURCE IMAGES  •  drop files here or click to select').pack(anchor='w',pady=(0,5))
        self.source_canvas = tk.Canvas(left,bg='#20242d',highlightthickness=0,width=230)
        source_scroll=ttk.Scrollbar(left,orient='vertical',command=self.source_canvas.yview)
        self.source_canvas.configure(yscrollcommand=source_scroll.set)
        source_scroll.pack(side='right',fill='y')
        self.source_canvas.pack(side='left',fill='both',expand=True)
        self.source_canvas.bind('<Button-1>',self.source_click)
        self.source_canvas.drop_target_register(DND_FILES)
        self.source_canvas.dnd_bind('<<Drop>>', self.drop_source_files)
        self.source_canvas.bind('<MouseWheel>',lambda e:self.source_canvas.yview_scroll(-int(e.delta/120),'units'))
        ttk.Label(right,text='SPRITESHEET  •  click to place  •  drag to swap/move').pack(anchor='w',pady=(0,5))
        self.canvas=tk.Canvas(right,bg='#20242d',highlightthickness=0)
        vscroll=ttk.Scrollbar(right,orient='vertical',command=self.canvas.yview)
        hscroll=ttk.Scrollbar(right,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vscroll.set,xscrollcommand=hscroll.set)
        vscroll.pack(side='right',fill='y')
        hscroll.pack(side='bottom',fill='x')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',self.cell_press)
        self.canvas.bind('<ButtonRelease-1>',self.cell_release)
        self.canvas.bind('<ButtonPress-3>',self.cell_clear)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        ttk.Label(self,textvariable=self.status,wraplength=1000).pack(fill='x',padx=12,pady=(0,5))
        self.log_visible = tk.BooleanVar(value=False)
        log_bar = ttk.Frame(self, padding=(10,0,10,5))
        log_bar.pack(fill='x')
        ttk.Checkbutton(log_bar, text='Show application log', variable=self.log_visible, command=self.toggle_log).pack(side='left')
        ttk.Button(log_bar, text='Copy log', command=self.copy_log).pack(side='right')
        self.log_frame = ttk.Frame(self, padding=(10,0,10,10))
        self.log_text = tk.Text(self.log_frame, height=7, bg='#101319', fg='#e7e9ed', insertbackground='#ffffff', wrap='word', state='disabled')
        self.log_text.pack(fill='both', expand=True)

        self.bind('<Delete>',self.delete_selected)
        self.bind('<Control-e>',lambda e:self.export_png())
        self.bind('<Control-s>',lambda e:self.save_project())

    def dims(self):
        try:
            c,r = int(self.columns.get()),int(self.rows.get())
            w=h=int(self.cell_size.get())
            if not (1<=c<=100 and 1<=r<=100 and 1<=w<=4096 and 1<=h<=4096): raise ValueError()
            return c,r,w,h
        except (ValueError,tk.TclError):
            messagebox.showerror('Invalid dimensions','Columns/rows must be 1–100 and cell dimensions 1–4096.')
            return None

    def rebuild_grid(self):
        dims=self.dims()
        if not dims:return
        c,r,w,h=dims
        target=c*r
        self.cells=(self.cells[:target]+[None]*max(0,target-len(self.cells)))
        self.redraw()

    def add_source_files(self, files):
        added = 0
        errors = []
        for p in files:
            p = os.path.abspath(os.path.normpath(p))
            if not os.path.isfile(p):
                continue
            try:
                with Image.open(p) as im:
                    im.verify()
                self.paths.append(p)
                added += 1
            except Exception as exc:
                errors.append(f'{p}: {exc}')
        if added:
            self.selected_source = len(self.paths) - 1
            self.log(f'Imported {added} source image(s).')
        if errors:
            self.log('Import errors: ' + '; '.join(errors))
            messagebox.showwarning('Some images could not be imported', '\n'.join(errors[:8]))
        self.redraw()

    def drop_source_files(self, event):
        # Tcl's splitlist correctly handles Windows paths with spaces and braces.
        files = self.tk.splitlist(event.data)
        self.add_source_files(files)
        return 'copy'

    def import_files(self):
        files = filedialog.askopenfilenames(title='Import sprite PNGs', filetypes=[('PNG files','*.png'),('Images','*.png *.webp *.jpg *.jpeg'),('All files','*.*')])
        self.add_source_files(files)

    def preview(self,path,size):
        key=(path,size)
        if key not in self.preview_cache:
            try:
                with Image.open(path) as src:
                    im=src.convert('RGBA')
                im.thumbnail((size,size),Image.Resampling.LANCZOS)
                self.preview_cache[key]=ImageTk.PhotoImage(im)
            except Exception:self.preview_cache[key]=None
        return self.preview_cache[key]

    def redraw(self):
        self.source_canvas.delete('all')
        for i,p in enumerate(self.paths):
            y=8+i*79
            self.source_canvas.create_rectangle(6,y,216,y+72,fill='#344a65' if i==self.selected_source else '#292e39',outline='#6e9de0' if i==self.selected_source else '#3a404b')
            pic=self.preview(p,62)
            if pic:self.source_canvas.create_image(41,y+36,image=pic)
            self.source_canvas.create_text(79,y+24,text=os.path.basename(p)[:22],anchor='w',fill='#f3f4f6',font=('Segoe UI',9))
            self.source_canvas.create_text(79,y+47,text=f'Image {i+1}',anchor='w',fill='#a9b4c4',font=('Segoe UI',9))
        self.source_canvas.configure(scrollregion=(0,0,225,max(100,len(self.paths)*79+8)))
        self.canvas.delete('all')
        dims=self.dims()
        if not dims:return
        cols,rows,w,h=dims
        display=min(160,max(52,int(720/max(cols,1))))
        self.tile=display
        self.gap=8
        self.pad=14
        for idx,p in enumerate(self.cells):
            col,row=idx%cols,idx//cols
            x=self.pad+col*(display+self.gap)
            y=self.pad+row*(display+self.gap)
            self.canvas.create_rectangle(x,y,x+display,y+display,fill='#303640',outline='#566070')
            # checkerboard
            sq=max(8,display//8)
            for yy in range(y,y+display,sq):
                for xx in range(x,x+display,sq):
                    if ((xx-x)//sq+(yy-y)//sq)%2==0:
                        self.canvas.create_rectangle(xx,yy,min(xx+sq,x+display),min(yy+sq,y+display),fill='#3d444f',outline='')
            if p is not None and p<len(self.paths):
                pic=self.preview(self.paths[p],display-8)
                if pic:self.canvas.create_image(x+display//2,y+display//2,image=pic)
            self.canvas.create_rectangle(x,y,x+display,y+display,outline='#6a7585')
            self.canvas.create_text(x+5,y+5,text=str(idx+1),anchor='nw',fill='#ffffff',font=('Segoe UI',9,'bold'))
        self.canvas.configure(scrollregion=(0,0,self.pad*2+cols*(display+self.gap),self.pad*2+rows*(display+self.gap)))
        self.output_label.configure(text=f'Output PNG: {cols*w} × {rows*h} px  •  {w} × {h} px per cell (no sheet resizing)')
        self.status.set(f'{cols} × {rows} cells  •  output {cols*w} × {rows*h} px  •  {sum(v is not None for v in self.cells)} occupied  •  Right-click a cell to clear')

    def source_click(self,event):
        idx=int((self.source_canvas.canvasy(event.y)-8)//79)
        if 0<=idx<len(self.paths):self.selected_source=idx;self.redraw()

    def index_at(self,event):
        dims=self.dims()
        if not dims:return None
        cols,rows,_,_=dims
        x=self.canvas.canvasx(event.x)-self.pad
        y=self.canvas.canvasy(event.y)-self.pad
        if x<0 or y<0:return None
        col=int(x//(self.tile+self.gap));row=int(y//(self.tile+self.gap))
        if col>=cols or row>=rows or x%(self.tile+self.gap)>=self.tile or y%(self.tile+self.gap)>=self.tile:return None
        return row*cols+col

    def cell_press(self,event):
        idx=self.index_at(event)
        self.drag_cell=idx
        self.drag_source=self.cells[idx] if idx is not None else None

    def cell_release(self,event):
        dest=self.index_at(event)
        src=self.drag_cell
        self.drag_cell=None
        if dest is None:return
        if src is not None and dest!=src and self.drag_source is not None:
            self.cells[src],self.cells[dest]=self.cells[dest],self.cells[src]
        elif self.selected_source is not None:
            self.cells[dest]=self.selected_source
        self.redraw()

    def cell_clear(self,event):
        idx=self.index_at(event)
        if idx is not None:self.cells[idx]=None;self.redraw()

    def delete_selected(self,event=None):
        # Right-click is the intended deletion control; keyboard Delete is deliberately inert.
        pass

    def compose(self):
        dims=self.dims()
        if not dims:return None
        cols,rows,w,h=dims
        if cols*w*rows*h>150_000_000:
            messagebox.showerror('Image too large','Output exceeds 150 million pixels. Reduce dimensions.')
            return None
        output=Image.new('RGBA',(cols*w,rows*h),(0,0,0,0))
        mode=self.fit_mode.get()
        cropped=[]
        for idx,source in enumerate(self.cells):
            if source is None:continue
            if source>=len(self.paths):continue
            path=self.paths[source]
            try:
                with Image.open(path) as src:im=src.convert('RGBA')
            except Exception as exc:
                messagebox.showerror('Missing image',f'{path}\n{exc}')
                return None
            if mode=='Stretch to cell':
                im=im.resize((w,h),Image.Resampling.LANCZOS)
            elif mode.startswith('Contain'):
                scale=min(w/im.width,h/im.height)
                if mode=='Contain (no upscaling)':scale=min(scale,1)
                new_size=(max(1,round(im.width*scale)),max(1,round(im.height*scale)))
                if new_size!=im.size:im=im.resize(new_size,Image.Resampling.LANCZOS)
            if im.width>w or im.height>h:
                cropped.append(f'{Path(path).name} ({im.width}x{im.height} in {w}x{h} cell)')
            # centered in each cell; overflow cropped by cell mask
            cell=Image.new('RGBA',(w,h),(0,0,0,0))
            cell.paste(im,((w-im.width)//2,(h-im.height)//2))
            output.alpha_composite(cell,((idx%cols)*w,(idx//cols)*h))
        if cropped and mode in ('Original pixels (no resize)','Center original (crop overflow)'):
            messagebox.showwarning('Sprites clipped', 'Some original-size sprites exceed their cells and will be cropped:\n'+'\n'.join(cropped[:8]))
        return output

    def toggle_log(self):
        if self.log_visible.get():
            self.log_frame.pack(fill='x', before=None)
        else:
            self.log_frame.pack_forget()

    def log(self, message):
        line = f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n'
        self.log_text.configure(state='normal')
        self.log_text.insert('end', line)
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log_text.get('1.0', 'end-1c'))
        self.status.set('Log copied to clipboard.')

    def _report_callback_exception(self, exc_type, exc_value, exc_tb):
        details = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        self.log(details.rstrip())
        self.log_visible.set(True)
        self.toggle_log()
        messagebox.showerror('Application error', 'An error occurred. Open the application log for details.')

    def export_png(self):
        output=self.compose()
        if output is None:return
        path=filedialog.asksaveasfilename(title='Export transparent spritesheet',defaultextension='.png',filetypes=[('PNG image','*.png')],initialfile='spritesheet.png')
        if not path:return
        try:
            output.save(path)
            self.status.set(f'Exported {output.width}×{output.height} PNG to {path}')
            self.log(f'Exported {output.width}x{output.height} PNG: {path}')
            messagebox.showinfo('Export complete',f'Saved spritesheet:\n{path}')
        except Exception as exc:
            self.log(f'Export failed: {exc}')
            messagebox.showerror('Export failed',str(exc))

    def save_project(self):
        path=filedialog.asksaveasfilename(title='Save project',defaultextension='.json',filetypes=[('SpriteSheet project','*.json')])
        if not path:return
        dims=self.dims()
        if not dims:return
        data={'version':1,'paths':self.paths,'cells':self.cells,'columns':dims[0],'rows':dims[1],'cell_width':dims[2],'cell_height':dims[3],'cell_size':dims[2],'fit_mode':self.fit_mode.get()}
        try:
            with open(path,'w',encoding='utf-8') as f:json.dump(data,f,indent=2)
            self.status.set(f'Project saved: {path}')
        except Exception as exc:messagebox.showerror('Save failed',str(exc))

    def open_project(self):
        path=filedialog.askopenfilename(title='Open project',filetypes=[('SpriteSheet project','*.json')])
        if not path:return
        try:
            with open(path,'r',encoding='utf-8') as f:data=json.load(f)
            self.paths=[str(p) for p in data['paths']]
            self.cells=[None if p is None else int(p) for p in data['cells']]
            self.columns.set(int(data['columns']))
            self.rows.set(int(data['rows']))
            self.cell_size.set(int(data.get('cell_size', data.get('cell_width',128))))
            self.fit_mode.set(data.get('fit_mode','Original pixels (no resize)'))
            self.selected_source=None
            self.preview_cache.clear()
            self.rebuild_grid()
            missing=[p for p in self.paths if not os.path.isfile(p)]
            if missing:messagebox.showwarning('Missing source files',f'{len(missing)} source image(s) cannot be found. Projects store file paths, not image bytes.')
        except Exception as exc:messagebox.showerror('Open failed',str(exc))

if __name__=='__main__':
    App().mainloop()
