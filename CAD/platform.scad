$fn=100;
in=25.4;

extra=120;
x=10*in;
y=12*in;

xtra=x+extra;
ytra=y+extra;

OD=22;
bolt_d=8;
lead_hole=10.2;
set_r=3.1/2;

nema_w=42.3;

module tx8(model=true){
    if(model){
        difference(){
            circle(d=OD);
            
            circle(d=lead_hole);
            
            for(i=[0:3]){
                rotate([0,0,90*i])
                translate([bolt_d,0,0])
                circle(set_r);
            }
        }
    }
    else {   
        circle(d=lead_hole);
            
        for(i=[0:3]){
            rotate([0,0,90*i])
            translate([bolt_d,0,0])
            circle(set_r);
        }
    }
    
}

difference(){
    union(){
        square([x,y],center=true);
        square([xtra,y],center=true);
        square([x,ytra],center=true);
    }
    translate([0,ytra/2-nema_w/2,0])
    tx8(false);
    translate([0,-ytra/2+nema_w/2,0])
    tx8(false);
}


