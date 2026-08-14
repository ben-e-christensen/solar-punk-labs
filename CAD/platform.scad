$fn=100;
in=25.4;

extra_x=80;
extra_y=120;

x=(15+1/32)*in;
y=(18+1/8)*in;

xtra=x+extra_x;
ytra=y+extra_y;

OD=22;
bolt_d=8;
lead_hole=10.2;
set_r=3.2/2;

nema_w=42.3;

// endstop dimensions
e_x=35;
e_y=11;
u_left=11.3;
u_right=17.7;
bh=28;

module endstop(model=true){
    if(model){
        difference(){
            square([e_x,e_y],center=true);
            translate([-bh/2,0,0])
            circle(set_r);
            translate([bh/2,0,0])
            circle(set_r);
        }
    } else {
        translate([-bh/2,0,0])
        circle(set_r);
        translate([bh/2,0,0])
        circle(set_r);
    }
}

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

module plate(bottom=true){
    if(bottom){
        difference(){
            union(){
                square([x,y-extra_y-6],center=true);
                square([x-extra_x-6,y],center=true);
           }
           translate([30,y/2-20,0])
           tx8(false);
           translate([-30,-y/2+20,0])
           tx8(false);
           translate([x/5,-y/2+20,0])
           endstop(false);
           translate([x/5,y/2-20,0])
           endstop(false);
        }
    } else {
       difference(){
            union(){
                square([x,y-extra_y-6],center=true);
                square([x-extra_x-6,y],center=true);
           }
           circle(1/2*in);
           translate([3*in,3*in,0])
           circle(1/2*in);
           translate([-3*in,3*in,0])
           circle(1/2*in);
           translate([3*in,-3*in,0])
           circle(1/2*in);
           translate([-3*in,-3*in,0])
           circle(1/2*in);
           translate([x/5,-y/2+20,0])
           endstop(false);
           translate([x/5,y/2-20,0])
           endstop(false);
           
           
           
           translate([0,y/2-nema_w/2,0])
           tx8(false);
           translate([0,-y/2+nema_w/2,0])
           tx8(false);
        }
    } 
}




endstop(false);
plate();




